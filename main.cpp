// Square Graph Builder, originally created by Jason Behrstock in 2015.
// The unchanged 2024 source is preserved in Git commit 9b02b7938c2a5ed766b3986af51a53c9a7e50bc3.
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
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
    std::set<Vertex> elements() const {
        return {first.first, first.second, second.first, second.second};
    }
};

bool sameNonedge(const Nonedge& a, const Nonedge& b) {
    return a == b || (a.first == b.second && a.second == b.first);
}

bool containsSquare(const std::vector<Square>& squares, const Square& candidate) {
    for (const auto& square : squares) {
        if ((sameNonedge(square.first, candidate.first) && sameNonedge(square.second, candidate.second)) ||
            (sameNonedge(square.first, candidate.second) && sameNonedge(square.second, candidate.first)))
            return true;
    }
    return false;
}

std::vector<Square> findSquares(const Graph& graph) {
    std::vector<Square> squares;
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
                    if (!containsSquare(squares, square))
                        squares.push_back(square);
                }
            }
        }
    }
    return squares;
}

bool adjacentSquares(const Square& a, const Square& b) {
    return sameNonedge(a.first, b.first) || sameNonedge(a.first, b.second) ||
           sameNonedge(a.second, b.first) || sameNonedge(a.second, b.second);
}

Graph buildSquareGraph(const std::vector<Square>& squares) {
    Graph result(squares.size());
    for (std::size_t i = 0; i < squares.size(); ++i)
        for (std::size_t j = i + 1; j < squares.size(); ++j)
            if (adjacentSquares(squares[i], squares[j]))
                boost::add_edge(i, j, result);
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

struct Analysis {
    std::vector<Square> squares;
    Graph square_graph;
    Components original_components, square_components;
    std::vector<std::set<Vertex>> supports;
    std::vector<std::size_t> component_square_counts;
    std::size_t largest_support = 0;
    std::size_t universal_vertices = 0;
    double average_support_ratio = 0;
    double largest_support_ratio = 0;
    bool cfs = false;
};

Analysis analyze(const Graph& graph) {
    Analysis result;
    const std::size_t n = boost::num_vertices(graph);
    result.original_components = findComponents(graph);
    result.squares = findSquares(graph);
    result.square_graph = buildSquareGraph(result.squares);
    result.square_components = findComponents(result.square_graph);
    result.supports.resize(result.square_components.count);
    result.component_square_counts.resize(result.square_components.count, 0);
    for (std::size_t i = 0; i < result.squares.size(); ++i) {
        const std::size_t component = result.square_components.labels[i];
        const auto elements = result.squares[i].elements();
        result.supports[component].insert(elements.begin(), elements.end());
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
    for (Vertex u = 0; u < n; ++u) {
        for (Vertex v = u + 1; v < n; ++v) {
            if (boost::edge(u, v, graph).second) {
                if (!first) output << ',';
                output << '(' << u + 1 << ',' << v + 1 << ')';
                first = false;
            }
        }
    }
    output << "]\n";
}

void describe(std::ostream& output, const Graph& graph, const Analysis& result,
              const sgb::Options& options) {
    if (!options.verbose && !options.debug)
        return;
    output << "Graph: ";
    writeGraph(output, graph);
    output << "Square graph: ";
    writeGraph(output, result.square_graph);
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
        const Analysis result = analyze(graph);
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
