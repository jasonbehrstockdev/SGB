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

using SquareKey = std::array<Vertex, 4>;

SquareKey canonicalSquare(const Square& square) {
    Nonedge first = canonicalNonedge(square.first);
    Nonedge second = canonicalNonedge(square.second);
    if (second < first)
        std::swap(first, second);
    return {{first.first, first.second, second.first, second.second}};
}

struct SquareHash {
    std::size_t operator()(const SquareKey& key) const {
        std::size_t seed = 0;
        for (Vertex vertex : key)
            seed = combineHash(seed, vertex);
        return seed;
    }
};

struct NonedgeHash {
    std::size_t operator()(const Nonedge& diagonal) const {
        return combineHash(combineHash(0, diagonal.first), diagonal.second);
    }
};

std::vector<Square> findSquares(const Graph& graph) {
    std::vector<Square> squares;
    std::unordered_set<SquareKey, SquareHash> seen;
    const auto vertices = boost::vertices(graph);
    for (auto v = vertices.first; v != vertices.second; ++v) {
        const auto neighbors = boost::adjacent_vertices(*v, graph);
        for (auto a = neighbors.first; a != neighbors.second; ++a) {
            auto b = a;
            for (++b; b != neighbors.second; ++b) {
                if (*a == *b || boost::edge(*a, *b, graph).second)
                    continue;
                const auto across = boost::adjacent_vertices(*b, graph);
                for (auto opposite = across.first; opposite != across.second; ++opposite) {
                    if (*opposite == *v || boost::edge(*opposite, *v, graph).second)
                        continue;
                    // The two diagonals are nonedges; the four perimeter edges
                    // exist exactly when a is also adjacent to opposite.
                    if (!boost::edge(*a, *opposite, graph).second)
                        continue;
                    const Square square = {{*v, *opposite}, {*a, *b}};
                    // Hash only the canonical key. Keep the original discovery
                    // order and diagonal orientation for stable square labels.
                    if (seen.insert(canonicalSquare(square)).second)
                        squares.push_back(square);
                }
            }
        }
    }
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

Analysis analyze(const Graph& graph, SquareGraphMode mode = SquareGraphMode::ComponentsOnly) {
    Analysis result;
    const std::size_t n = boost::num_vertices(graph);
    result.original_components = findComponents(graph);
    result.squares = findSquares(graph);
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
    for (Vertex v = 0; v < n; ++v) {
        bool universal = true;
        for (Vertex u = 0; u < n; ++u) {
            if (u != v && !boost::edge(u, v, graph).second) {
                universal = false;
                break;
            }
        }
        if (universal)
            ++result.universal_vertices;
    }
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
