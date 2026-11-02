// Square Graph Builder, originally created by Jason Behrstock in 2015.
// The unchanged 2024 source is preserved in Git commit 9b02b7938c2a5ed766b3986af51a53c9a7e50bc3.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>
#include <sys/stat.h>

#include <boost/graph/adjacency_list.hpp>
#include <boost/graph/connected_components.hpp>
#include "flags.h"
#include "input.h"

namespace {
using Graph = boost::adjacency_list<boost::listS, boost::vecS, boost::undirectedS>;
using Vertex = boost::graph_traits<Graph>::vertex_descriptor;
using Nonedge = std::pair<Vertex, Vertex>;

struct Square {
    Nonedge first, second;
};

Nonedge canonicalNonedge(Nonedge diagonal) {
    if (diagonal.second < diagonal.first)
        std::swap(diagonal.first, diagonal.second);
    return diagonal;
}

std::size_t combineHash(std::size_t seed, Vertex vertex) {
    return seed ^ (std::hash<Vertex>()(vertex) + 0x9e3779b9U + (seed << 6) + (seed >> 2));
}

struct NonedgeHash {
    std::size_t operator()(const Nonedge& diagonal) const {
        return combineHash(combineHash(0, diagonal.first), diagonal.second);
    }
};

enum class SquareSearchStrategy { Auto, Wedges, MissingEdges };

struct SquareSearchMetrics {
    SquareSearchStrategy strategy = SquareSearchStrategy::Auto;
    bool dense_adjacency = false;
    std::size_t vertices = 0, edges = 0, nonedges = 0, active_vertices = 0;
    std::size_t wedge_visits = 0, wedge_pairs = 0, missing_edge_pairs = 0;
    std::size_t squares = 0, radix_passes = 0;
    long double estimated_wedge_work = 0, estimated_missing_edge_work = 0;
};

constexpr std::size_t defaultAdjacencyBudget = 64 * 1024 * 1024;

struct SearchNeighbor {
    Vertex vertex;
    std::size_t original_rank;
};
using SearchNeighbors = std::vector<std::vector<SearchNeighbor>>;

std::size_t unorderedPairCount(std::size_t n) {
    if (n < 2) return 0;
    const std::size_t first = n % 2 ? n : n / 2;
    const std::size_t second = n % 2 ? (n - 1) / 2 : n - 1;
    if (second && first > std::numeric_limits<std::size_t>::max() / second)
        throw std::length_error("Vertex-pair count exceeds the supported size");
    return first * second;
}

void incrementSearchCounter(std::size_t& value) {
    if (value == std::numeric_limits<std::size_t>::max())
        throw std::length_error("Square-search operation counter overflow");
    ++value;
}

// Edge membership is constant-time with the bounded bit matrix, or expected
// constant-time with hashed adjacency when the matrix would exceed its budget.
// Only nonuniversal vertices participate: a universal vertex lies in no induced C4.
class SearchAdjacency {
    std::size_t words;
    std::vector<std::uint64_t> matrix;
    std::vector<std::unordered_set<Vertex>> hashed;
    bool dense;
public:
    SearchAdjacency(const SearchNeighbors& neighbors, std::size_t budget)
        : words(neighbors.size() / 64 + (neighbors.size() % 64 != 0)),
          dense(!neighbors.empty() && words <= budget / sizeof(std::uint64_t) / neighbors.size()) {
        if (dense) {
            matrix.assign(neighbors.size() * words, 0);
            for (Vertex u = 0; u < neighbors.size(); ++u)
                for (const auto& item : neighbors[u])
                    matrix[u * words + item.vertex / 64] |= std::uint64_t(1) << (item.vertex % 64);
        } else {
            hashed.resize(neighbors.size());
            for (Vertex u = 0; u < neighbors.size(); ++u) {
                if (neighbors[u].empty()) continue;
                hashed[u].reserve(neighbors[u].size());
                for (const auto& item : neighbors[u]) hashed[u].insert(item.vertex);
            }
        }
    }

    bool edge(Vertex u, Vertex v) const {
        return dense ? (matrix[u * words + v / 64] & (std::uint64_t(1) << (v % 64))) != 0
                     : hashed[u].find(v) != hashed[u].end();
    }

    bool usesMatrix() const { return dense; }
};

struct OrderedSquare {
    Square square;
    std::array<std::size_t, 4> order;
};

// The original walk first finds a square at its minimum vertex u, then orders
// the two neighbors by their positions in N(u), then the opposite vertex by
// its position in the later neighbor's list. Four stable counting-sort passes
// restore that exact order in O(n + S), including the original orientations.
void restoreSquareOrder(std::vector<OrderedSquare>& found, std::size_t n,
                        SquareSearchMetrics* metrics) {
    if (found.size() < 2) return;
    std::vector<OrderedSquare> scratch(found.size());
    std::vector<std::size_t> offsets(n);
    for (int field = 3; field >= 0; --field) {
        std::fill(offsets.begin(), offsets.end(), 0);
        for (const auto& item : found) ++offsets[item.order[field]];
        std::size_t position = 0;
        for (auto& count : offsets) {
            const std::size_t size = count;
            count = position;
            position += size;
        }
        for (const auto& item : found) scratch[offsets[item.order[field]]++] = item;
        found.swap(scratch);
        if (metrics) incrementSearchCounter(metrics->radix_passes);
    }
}

std::vector<Square> findSquares(const Graph& graph,
                               SquareSearchStrategy requested = SquareSearchStrategy::Auto,
                               std::size_t adjacency_budget_bytes = defaultAdjacencyBudget,
                               SquareSearchMetrics* metrics = nullptr) {
    const std::size_t n = boost::num_vertices(graph);
    if (metrics) {
        *metrics = SquareSearchMetrics();
        metrics->vertices = n;
        metrics->edges = boost::num_edges(graph);
    }
    SearchNeighbors neighbors(n);
    std::vector<Vertex> active;
    std::vector<bool> universal(n, false);
    for (Vertex u = 0; u < n; ++u) {
        // All input/generator paths normalize to a simple undirected graph.
        universal[u] = boost::degree(u, graph) == n - 1;
        if (!universal[u]) active.push_back(u);
    }
    std::size_t active_edges = 0;
    for (Vertex u : active) {
        const auto range = boost::adjacent_vertices(u, graph);
        std::size_t rank = 0;
        for (auto it = range.first; it != range.second; ++it, ++rank) {
            if (universal[*it]) continue;
            neighbors[u].push_back({*it, rank});
            if (*it > u) ++active_edges;
        }
    }
    const std::size_t possible_pairs = unorderedPairCount(active.size());
    if (active_edges > possible_pairs)
        throw std::logic_error("Square search requires a simple graph");
    const std::size_t missing = possible_pairs - active_edges;
    long double wedge_work = 0;
    for (Vertex u : active)
        for (const auto& neighbor : neighbors[u])
            if (neighbor.vertex > u) wedge_work += neighbors[neighbor.vertex].size();
    // This is a work heuristic, not a bound on the wedge candidate-pair term.
    // Complement search scans active pairs and makes at most four edge probes
    // for each pair of nonedges. Estimates use wide arithmetic, not q*q integers.
    const long double missing_work = static_cast<long double>(possible_pairs) +
        2.0L * missing * (missing ? missing - 1 : 0);
    const SquareSearchStrategy strategy = requested == SquareSearchStrategy::Auto
        ? (missing_work < wedge_work ? SquareSearchStrategy::MissingEdges : SquareSearchStrategy::Wedges)
        : requested;
    if (metrics) {
        metrics->strategy = strategy;
        metrics->active_vertices = active.size();
        metrics->nonedges = missing;
        metrics->estimated_wedge_work = wedge_work;
        metrics->estimated_missing_edge_work = missing_work;
    }
    if (active.size() < 4 || missing < 2 || wedge_work == 0) return {};
    const SearchAdjacency adjacency(neighbors, adjacency_budget_bytes);
    if (metrics) metrics->dense_adjacency = adjacency.usesMatrix();
    std::vector<OrderedSquare> found;

    if (strategy == SquareSearchStrategy::Wedges) {
        struct Wedge {
            Vertex neighbor;
            std::size_t first_rank, opposite_rank;
        };
        std::vector<std::vector<Wedge>> buckets(n);
        std::vector<Vertex> touched;
        for (Vertex u : active) {
            touched.clear();
            for (const auto& first : neighbors[u]) {
                const Vertex w = first.vertex;
                if (w <= u) continue;
                for (const auto& second : neighbors[w]) {
                    if (metrics) incrementSearchCounter(metrics->wedge_visits);
                    const Vertex v = second.vertex;
                    if (v <= u || adjacency.edge(u, v)) continue;
                    if (buckets[v].empty()) touched.push_back(v);
                    buckets[v].push_back({w, first.original_rank, second.original_rank});
                }
            }
            for (Vertex v : touched) {
                const auto& bucket = buckets[v];
                for (std::size_t i = 0; i < bucket.size(); ++i)
                    for (std::size_t j = i + 1; j < bucket.size(); ++j) {
                        if (metrics) incrementSearchCounter(metrics->wedge_pairs);
                        const auto& a = bucket[i];
                        const auto& b = bucket[j];
                        if (adjacency.edge(a.neighbor, b.neighbor)) continue;
                        // u is the unique smallest vertex, so no deduplication
                        // table is needed. Bucket order is the order in N(u).
                        found.push_back({{{u, v}, {a.neighbor, b.neighbor}},
                                         {{u, a.first_rank, b.first_rank, b.opposite_rank}}});
                    }
                buckets[v].clear();
            }
        }
    } else {
        std::vector<Nonedge> nonedges;
        nonedges.reserve(missing);
        for (std::size_t i = 0; i < active.size(); ++i)
            for (std::size_t j = i + 1; j < active.size(); ++j)
                if (!adjacency.edge(active[i], active[j])) nonedges.push_back({active[i], active[j]});
        // Dense-path ranks are needed only if a square actually exists. Hash
        // lookup keeps order restoration expected-linear in the graph and output.
        std::vector<std::unordered_map<Vertex, std::size_t>> ranks;
        for (std::size_t i = 0; i < nonedges.size(); ++i)
            for (std::size_t j = i + 1; j < nonedges.size(); ++j) {
                if (metrics) incrementSearchCounter(metrics->missing_edge_pairs);
                const Vertex u = nonedges[i].first, v = nonedges[i].second;
                Vertex a = nonedges[j].first, b = nonedges[j].second;
                if (u == a || u == b || v == a || v == b) continue;
                if (!adjacency.edge(u, a) || !adjacency.edge(u, b) ||
                    !adjacency.edge(v, a) || !adjacency.edge(v, b)) continue;
                if (ranks.empty()) {
                    ranks.resize(n);
                    for (Vertex vertex : active) {
                        ranks[vertex].reserve(neighbors[vertex].size());
                        for (const auto& item : neighbors[vertex])
                            ranks[vertex].emplace(item.vertex, item.original_rank);
                    }
                }
                // Nonedges were generated lexicographically; hence u is the
                // minimum square vertex. Orient its two neighbors as before.
                if (ranks[u].at(b) < ranks[u].at(a)) std::swap(a, b);
                found.push_back({{{u, v}, {a, b}},
                                 {{u, ranks[u].at(a), ranks[u].at(b), ranks[b].at(v)}}});
            }
    }
    restoreSquareOrder(found, n, metrics);
    std::vector<Square> squares;
    squares.reserve(found.size());
    for (const auto& item : found) squares.push_back(item.square);
    if (metrics) metrics->squares = squares.size();
    return squares;
}

using SquareIndex = std::unordered_map<Nonedge, std::vector<std::size_t>, NonedgeHash>;

SquareIndex indexSquares(const std::vector<Square>& squares) {
    SquareIndex index;
    for (std::size_t i = 0; i < squares.size(); ++i) {
        index[canonicalNonedge(squares[i].first)].push_back(i);
        index[canonicalNonedge(squares[i].second)].push_back(i);
    }
    return index;
}

Graph buildSquareGraph(std::size_t square_count, const SquareIndex& index) {
    Graph result(square_count);
    for (const auto& entry : index) {
        const auto& bucket = entry.second;
        for (std::size_t i = 0; i < bucket.size(); ++i)
            for (std::size_t j = i + 1; j < bucket.size(); ++j)
                boost::add_edge(bucket[i], bucket[j], result);
    }
    // Distinct induced squares cannot share both diagonals, so each edge is
    // emitted exactly once even when different buckets connect transitively.
    return result;
}

struct Components {
    std::vector<std::size_t> labels;
    std::size_t count = 0;
};

Components findComponents(const Graph& graph) {
    Components result;
    result.labels.resize(boost::num_vertices(graph));
    if (!result.labels.empty())
        result.count = boost::connected_components(graph, result.labels.data());
    return result;
}

class DisjointSets {
    std::vector<std::size_t> parent, sizes;
public:
    explicit DisjointSets(std::size_t n) : parent(n), sizes(n, 1) {
        for (std::size_t i = 0; i < n; ++i)
            parent[i] = i;
    }

    std::size_t root(std::size_t vertex) {
        while (parent[vertex] != vertex) {
            parent[vertex] = parent[parent[vertex]];
            vertex = parent[vertex];
        }
        return vertex;
    }

    void unite(std::size_t a, std::size_t b) {
        a = root(a);
        b = root(b);
        if (a == b)
            return;
        if (sizes[a] < sizes[b])
            std::swap(a, b);
        parent[b] = a;
        sizes[a] += sizes[b];
    }
};

Components findSquareComponents(std::size_t square_count, const SquareIndex& index) {
    DisjointSets sets(square_count);
    // Each diagonal bucket is a clique in the literal square graph. A star
    // has the same connectivity and needs only bucket.size() - 1 unions.
    for (const auto& entry : index) {
        const auto& bucket = entry.second;
        for (std::size_t i = 1; i < bucket.size(); ++i)
            sets.unite(bucket[0], bucket[i]);
    }
    Components result;
    result.labels.resize(square_count);
    std::vector<std::size_t> labels(square_count, square_count);
    // Assign labels by first square occurrence, independently of hash order
    // or union representatives, matching the prior graph traversal's labels.
    for (std::size_t i = 0; i < square_count; ++i) {
        const std::size_t representative = sets.root(i);
        if (labels[representative] == square_count)
            labels[representative] = result.count++;
        result.labels[i] = labels[representative];
    }
    return result;
}

enum class SquareGraphMode { ComponentsOnly, Materialize };

struct Analysis {
    std::vector<Square> squares;
    // Null means the literal square graph was not requested. Component labels
    // always refer to that graph, never to a substitute graph of union edges.
    std::unique_ptr<Graph> square_graph;
    Components original_components, square_components;
    std::vector<std::set<Vertex>> supports;
    std::vector<std::size_t> component_square_counts;
    std::size_t largest_support = 0;
    std::size_t universal_vertices = 0;
    double average_support_ratio = 0;
    double largest_support_ratio = 0;
    bool cfs = false;
};

Analysis analyze(const Graph& graph, SquareGraphMode mode = SquareGraphMode::ComponentsOnly,
                 SquareSearchStrategy strategy = SquareSearchStrategy::Auto,
                 std::size_t adjacency_budget_bytes = defaultAdjacencyBudget,
                 SquareSearchMetrics* metrics = nullptr) {
    Analysis result;
    const std::size_t n = boost::num_vertices(graph);
    result.original_components = findComponents(graph);
    result.squares = findSquares(graph, strategy, adjacency_budget_bytes, metrics);
    const SquareIndex index = indexSquares(result.squares);
    result.square_components = findSquareComponents(result.squares.size(), index);
    if (mode == SquareGraphMode::Materialize)
        result.square_graph.reset(new Graph(buildSquareGraph(result.squares.size(), index)));
    result.supports.resize(result.square_components.count);
    result.component_square_counts.resize(result.square_components.count, 0);
    for (std::size_t i = 0; i < result.squares.size(); ++i) {
        const std::size_t component = result.square_components.labels[i];
        const auto& square = result.squares[i];
        auto& support = result.supports[component];
        support.insert(square.first.first);
        support.insert(square.first.second);
        support.insert(square.second.first);
        support.insert(square.second.second);
        ++result.component_square_counts[component];
    }
    long double support_sum = 0;
    for (const auto& support : result.supports) {
        result.largest_support = std::max(result.largest_support, support.size());
        support_sum += support.size();
    }
    if (n != 0) {
        result.largest_support_ratio = static_cast<double>(result.largest_support) / n;
        if (!result.supports.empty())
            result.average_support_ratio = static_cast<double>(support_sum / result.supports.size() / n);
    }
    // A universal vertex cannot lie in an induced square. Exclude the complete
    // join factor only from the CFS target, never from literal square supports.
    for (Vertex v = 0; v < n; ++v)
        if (boost::degree(v, graph) == n - 1) ++result.universal_vertices;
    result.cfs = result.original_components.count == 1 && !result.supports.empty() &&
                 result.largest_support == n - result.universal_vertices;
    return result;
}

Graph fromParsedGraph(const sgb::ParsedGraph& input) {
    Graph graph(input.vertices);
    for (const auto& edge : input.edges)
        boost::add_edge(edge.first, edge.second, graph);
    return graph;
}

Graph erdosRenyi(std::size_t n, double probability, std::mt19937_64& generator) {
    Graph graph(n);
    std::bernoulli_distribution include(probability);
    for (Vertex i = 0; i < n; ++i)
        for (Vertex j = i + 1; j < n; ++j)
            if (include(generator))
                boost::add_edge(i, j, graph);
    return graph;
}

Graph smallWorld(std::size_t n, std::size_t degree, double probability,
                 std::mt19937_64& generator) {
    Graph graph(n);
    if (degree == 0)
        return graph;
    if (degree == n - 1) {
        for (Vertex i = 0; i < n; ++i)
            for (Vertex j = i + 1; j < n; ++j)
                boost::add_edge(i, j, graph);
        return graph;
    }
    // Validated even degree gives a simple ring lattice. Visit each original
    // clockwise edge once, rewiring to a uniformly chosen current nonneighbor.
    std::vector<std::pair<Vertex, Vertex>> lattice_edges;
    for (Vertex i = 0; i < n; ++i) {
        for (std::size_t offset = 1; offset <= degree / 2; ++offset) {
            const Vertex j = i >= n - offset ? i - (n - offset) : i + offset;
            boost::add_edge(i, j, graph);
            lattice_edges.push_back({i, j});
        }
    }
    std::bernoulli_distribution rewire(probability);
    for (const auto& edge : lattice_edges) {
        if (!rewire(generator))
            continue;
        std::vector<Vertex> candidates;
        for (Vertex target = 0; target < n; ++target)
            if (target != edge.first && !boost::edge(edge.first, target, graph).second)
                candidates.push_back(target);
        // A source can become saturated after earlier rewiring. Keeping its
        // current edge avoids rejection loops and preserves the edge count.
        if (candidates.empty())
            continue;
        std::uniform_int_distribution<std::size_t> choose(0, candidates.size() - 1);
        const Vertex target = candidates[choose(generator)];
        boost::remove_edge(edge.first, edge.second, graph);
        boost::add_edge(edge.first, target, graph);
    }
    return graph;
}

void writeGraph(std::ostream& output, const Graph& graph) {
    output << '[';
    const std::size_t n = boost::num_vertices(graph);
    for (Vertex v = 0; v < n; ++v) {
        if (v != 0) output << ',';
        output << v + 1;
    }
    output << "] [";
    bool first = true;
    std::vector<Vertex> neighbors;
    for (Vertex u = 0; u < n; ++u) {
        neighbors.clear();
        const auto adjacent = boost::adjacent_vertices(u, graph);
        for (auto v = adjacent.first; v != adjacent.second; ++v)
            if (*v > u)
                neighbors.push_back(*v);
        // Emit the same lexicographic ordering as before, without querying
        // every absent edge (especially costly for a large square graph).
        std::sort(neighbors.begin(), neighbors.end());
        for (Vertex v : neighbors) {
            if (!first) output << ',';
            output << '(' << u + 1 << ',' << v + 1 << ')';
            first = false;
        }
    }
    output << "]\n";
}

void describe(std::ostream& output, const Graph& graph, const Analysis& result,
              const sgb::Options& options) {
    if (!options.verbose && !options.debug)
        return;
    if (!result.square_graph)
        throw std::logic_error("Verbose output requires the materialized square graph");
    output << "Graph: ";
    writeGraph(output, graph);
    output << "Square graph: ";
    writeGraph(output, *result.square_graph);
    if (options.debug) {
        for (std::size_t i = 0; i < result.squares.size(); ++i) {
            const auto& square = result.squares[i];
            output << "Square[" << i + 1 << "] diagonals=(" << square.first.first + 1
                   << ',' << square.first.second + 1 << "),(" << square.second.first + 1
                   << ',' << square.second.second + 1 << ")\n";
        }
    }
    for (std::size_t component = 0; component < result.supports.size(); ++component) {
        output << "component " << component + 1 << " contains "
               << result.component_square_counts[component] << " squares supported on "
               << result.supports[component].size() << " original vertices:";
        for (Vertex v : result.supports[component]) output << ' ' << v + 1;
        output << '\n';
    }
    if (result.original_components.count > 1)
        output << "This graph is disconnected\n";
    output << (result.cfs ? "This graph is CFS\n" : "This graph is not CFS\n");
}

double density(const Graph& graph) {
    const std::size_t n = boost::num_vertices(graph);
    if (n < 2) return 0;
    return static_cast<double>(2.0L * boost::num_edges(graph) /
                               (static_cast<long double>(n) * (n - 1)));
}

struct Summary {
    std::size_t trials = 0, cfs = 0, first_n = 0;
    double first_p = 0, first_alpha = 0;
    bool mixed_n = false, mixed_p = false, mixed_alpha = false;
    long double support_sum = 0, largest_sum = 0;

    void add(std::size_t n, double p, double alpha, const Analysis& result) {
        if (trials == 0) {
            first_n = n; first_p = p; first_alpha = alpha;
        } else {
            mixed_n = mixed_n || first_n != n;
            mixed_p = mixed_p || first_p != p;
            mixed_alpha = mixed_alpha || first_alpha != alpha;
        }
        ++trials;
        if (result.cfs) ++cfs;
        support_sum += result.average_support_ratio;
        largest_sum += result.largest_support_ratio;
    }

    void print(std::ostream& output) const {
        output << "p=";
        if (mixed_p) output << "mixed"; else output << first_p;
        output << ", alpha=";
        if (mixed_alpha) output << "mixed"; else output << first_alpha;
        output << ", n=";
        if (mixed_n) output << "mixed"; else output << first_n;
        output << ", trials=" << trials << ", #CFS=" << cfs
               << ", PercentCFS=" << 100.0L * cfs / trials
               << ", AvgSupport=" << support_sum / trials
               << ", LargestSupport=" << largest_sum / trials << '\n';
    }
};

bool sameExistingFile(const std::string& input, const std::string& output) {
    // stat follows symlinks and also recognizes hard links to the input.
    struct stat input_stat, output_stat;
    return ::stat(input.c_str(), &input_stat) == 0 && ::stat(output.c_str(), &output_stat) == 0 &&
           input_stat.st_dev == output_stat.st_dev && input_stat.st_ino == output_stat.st_ino;
}

int run(const sgb::Options& options) {
    std::ifstream input;
    if (options.file_mode) {
        input.open(options.input_path);
        if (!input) throw std::runtime_error("Cannot open input file: " + options.input_path);
    }
    std::ofstream exported;
    if (options.export_graphs) {
        if (options.file_mode && sameExistingFile(options.input_path, "graphsanalyzed.txt"))
            throw std::runtime_error("Input and export file must be different files");
        exported.open("graphsanalyzed.txt", std::ios::app);
        if (!exported) throw std::runtime_error("Cannot open export file: graphsanalyzed.txt");
    }
    std::mt19937_64 generator;
    if (!options.file_mode) {
        std::uint64_t seed = options.seed;
        if (!options.has_seed) {
            std::random_device entropy;
            seed = (static_cast<std::uint64_t>(entropy()) << 32) ^ entropy();
        }
        generator.seed(seed);
        std::cerr << "Seed=" << seed << '\n';
    }
    std::cout << std::setprecision(12);
    if (options.full)
        std::cout << "n,p,alpha,CFS,num_squares,num_comp,ratio_comp_avg,ratio_largest_comp,status\n";
    Summary summary;
    const auto process = [&](const Graph& graph) {
        const Analysis result = analyze(graph, options.verbose || options.debug
            ? SquareGraphMode::Materialize : SquareGraphMode::ComponentsOnly);
        const std::size_t n = boost::num_vertices(graph);
        const double p = options.file_mode ? density(graph) : options.probability;
        const double alpha = options.file_mode ? p * std::sqrt(static_cast<double>(n)) : options.alpha;
        if (options.export_graphs) {
            writeGraph(exported, graph);
            exported.flush();
            if (!exported) throw std::runtime_error("Failed to write export file: graphsanalyzed.txt");
        }
        describe(options.full ? std::cerr : std::cout, graph, result, options);
        if (options.full) {
            const char* status = n == 0 ? "empty" : result.original_components.count > 1 ? "disconnected" : "connected";
            std::cout << n << ',' << p << ',' << alpha << ',' << result.cfs << ','
                      << result.squares.size() << ',' << result.square_components.count << ','
                      << result.average_support_ratio << ',' << result.largest_support_ratio << ',' << status << '\n';
        }
        summary.add(n, p, alpha, result);
    };
    if (options.file_mode) {
        std::string line;
        std::size_t line_number = 0;
        while (std::getline(input, line)) {
            ++line_number;
            sgb::ParsedGraph parsed;
            try {
                parsed = sgb::parse_graph(line);
            } catch (const std::exception& error) {
                throw std::runtime_error(options.input_path + ":" + std::to_string(line_number) + ": " + error.what());
            }
            process(fromParsedGraph(parsed));
        }
        if (input.bad() || (!input.eof() && input.fail()))
            throw std::runtime_error("Failed to read input file: " + options.input_path);
        if (summary.trials == 0)
            throw std::runtime_error("Input file contains no graphs: " + options.input_path);
    } else {
        for (std::size_t trial = 0; trial < options.trials; ++trial) {
            process(options.small_world
                ? smallWorld(options.vertices, options.mean_degree, options.probability, generator)
                : erdosRenyi(options.vertices, options.probability, generator));
        }
    }
    if (!options.full) summary.print(std::cout);
    if (options.export_graphs) {
        exported.close();
        if (!exported) throw std::runtime_error("Failed to close export file: graphsanalyzed.txt");
    }
    std::cout.flush();
    if (!std::cout) throw std::runtime_error("Failed to write standard output");
    return 0;
}
} // namespace

int main(int argc, const char* argv[]) {
    try {
        const sgb::Options options = sgb::parse_options(argc, argv);
        if (options.help) {
            std::cout << sgb::usage();
            std::cout.flush();
            return std::cout ? 0 : 1;
        }
        return run(options);
    } catch (const std::exception& error) {
        std::cerr << "SGB: " << error.what() << '\n';
        return 1;
    }
}
