// Independent structural checks for square-enumeration/connectivity changes.
// The application is included only to exercise its private analysis result.
// The oracle enumerates every four-vertex subset and uses pairwise adjacency
// plus breadth-first search, rather than the application's hash/union pipeline.
#define main sgb_application_main
#include "../main.cpp"
#undef main

#include <array>
#include <numeric>
#include <queue>
#include <sstream>

namespace structural_tests {
using Key = std::array<std::size_t, 4>;

void require(bool condition, const std::string& name, const std::string& message) {
    if (!condition) throw std::runtime_error(name + ": " + message);
}

Key key(std::size_t a, std::size_t b, std::size_t c, std::size_t d) {
    if (a > b) std::swap(a, b);
    if (c > d) std::swap(c, d);
    if (std::make_pair(a, b) > std::make_pair(c, d)) {
        std::swap(a, c);
        std::swap(b, d);
    }
    return {{a, b, c, d}};
}

bool adjacent(const Key& a, const Key& b) {
    for (std::size_t i : {std::size_t(0), std::size_t(2)})
        for (std::size_t j : {std::size_t(0), std::size_t(2)})
            if (a[i] == b[j] && a[i + 1] == b[j + 1]) return true;
    return false;
}

std::vector<std::size_t> breadthFirstLabels(const std::vector<std::vector<std::size_t>>& neighbors) {
    const std::size_t missing = neighbors.size();
    std::vector<std::size_t> labels(neighbors.size(), missing);
    std::size_t component = 0;
    for (std::size_t start = 0; start < neighbors.size(); ++start) {
        if (labels[start] != missing) continue;
        std::queue<std::size_t> pending;
        pending.push(start);
        labels[start] = component;
        while (!pending.empty()) {
            const auto current = pending.front();
            pending.pop();
            for (auto next : neighbors[current]) {
                if (labels[next] != missing) continue;
                labels[next] = component;
                pending.push(next);
            }
        }
        ++component;
    }
    return labels;
}

std::size_t componentCount(const std::vector<std::size_t>& labels) {
    return labels.empty() ? 0 : *std::max_element(labels.begin(), labels.end()) + 1;
}

void check(const Graph& graph, const std::string& name) {
    const auto compact = analyze(graph, SquareGraphMode::ComponentsOnly);
    const auto materialized = analyze(graph, SquareGraphMode::Materialize);
    require(!compact.square_graph, name, "component-only mode materialized a graph");
    require(bool(materialized.square_graph), name, "literal graph was not materialized");
    const std::size_t n = boost::num_vertices(graph);
    std::vector<std::vector<bool>> matrix(n, std::vector<bool>(n, false));
    std::vector<std::vector<std::size_t>> original_neighbors(n);
    const auto input_edges = boost::edges(graph);
    for (auto it = input_edges.first; it != input_edges.second; ++it) {
        const auto u = boost::source(*it, graph), v = boost::target(*it, graph);
        matrix[u][v] = matrix[v][u] = true;
        original_neighbors[u].push_back(v);
        original_neighbors[v].push_back(u);
    }

    // Recognize an induced C4 by degree two on its four vertices. This does
    // not use the production neighbor-walk candidate enumeration.
    std::set<Key> expected_squares;
    for (std::size_t a = 0; a < n; ++a)
    for (std::size_t b = a + 1; b < n; ++b)
    for (std::size_t c = b + 1; c < n; ++c)
    for (std::size_t d = c + 1; d < n; ++d) {
        const int ab = matrix[a][b], ac = matrix[a][c], ad = matrix[a][d];
        const int bc = matrix[b][c], bd = matrix[b][d], cd = matrix[c][d];
        if (ab + ac + ad != 2 || ab + bc + bd != 2 ||
            ac + bc + cd != 2 || ad + bd + cd != 2) continue;
        const std::array<std::size_t, 4> vertices = {{a, b, c, d}};
        std::vector<std::size_t> diagonals;
        for (std::size_t i = 0; i < vertices.size(); ++i)
            for (std::size_t j = i + 1; j < vertices.size(); ++j)
                if (!matrix[vertices[i]][vertices[j]]) {
                    diagonals.push_back(vertices[i]);
                    diagonals.push_back(vertices[j]);
                }
        require(diagonals.size() == 4, name, "oracle diagonal count");
        expected_squares.insert(key(diagonals[0], diagonals[1], diagonals[2], diagonals[3]));
    }

    std::vector<Key> actual_squares;
    for (const auto& square : compact.squares)
        actual_squares.push_back(key(square.first.first, square.first.second,
                                     square.second.first, square.second.second));
    require(actual_squares.size() == expected_squares.size(), name, "square count/duplicates");
    require(std::set<Key>(actual_squares.begin(), actual_squares.end()) == expected_squares,
            name, "complete square set");
    require(materialized.squares.size() == actual_squares.size(), name, "mode square count");
    for (std::size_t i = 0; i < actual_squares.size(); ++i) {
        const auto& square = materialized.squares[i];
        require(actual_squares[i] == key(square.first.first, square.first.second,
                                        square.second.first, square.second.second),
                name, "mode square ordering");
    }

    std::vector<std::vector<std::size_t>> square_neighbors(actual_squares.size());
    std::set<std::pair<std::size_t, std::size_t>> expected_edges;
    for (std::size_t i = 0; i < actual_squares.size(); ++i)
        for (std::size_t j = i + 1; j < actual_squares.size(); ++j)
            if (adjacent(actual_squares[i], actual_squares[j])) {
                expected_edges.insert({i, j});
                square_neighbors[i].push_back(j);
                square_neighbors[j].push_back(i);
            }
    require(boost::num_vertices(*materialized.square_graph) == actual_squares.size(),
            name, "literal square vertex count");
    std::set<std::pair<std::size_t, std::size_t>> actual_edges;
    const auto square_edges = boost::edges(*materialized.square_graph);
    for (auto it = square_edges.first; it != square_edges.second; ++it) {
        auto u = boost::source(*it, *materialized.square_graph);
        auto v = boost::target(*it, *materialized.square_graph);
        if (u > v) std::swap(u, v);
        require(u < v && v < actual_squares.size(), name, "invalid literal square edge");
        require(actual_edges.insert({u, v}).second, name, "duplicate literal square edge");
    }
    require(actual_edges == expected_edges, name, "complete literal square edge set");

    const auto square_labels = breadthFirstLabels(square_neighbors);
    const auto original_labels = breadthFirstLabels(original_neighbors);
    const auto count = componentCount(square_labels);
    std::vector<std::set<Vertex>> supports(count);
    std::vector<std::size_t> counts(count, 0);
    for (std::size_t i = 0; i < actual_squares.size(); ++i) {
        supports[square_labels[i]].insert(actual_squares[i].begin(), actual_squares[i].end());
        ++counts[square_labels[i]];
    }
    std::size_t universal = 0, largest = 0, support_sum = 0;
    for (std::size_t u = 0; u < n; ++u)
        if (original_neighbors[u].size() == n - 1) ++universal;
    for (const auto& support : supports) {
        largest = std::max(largest, support.size());
        support_sum += support.size();
    }
    const bool expected_cfs = componentCount(original_labels) == 1 && count != 0 &&
                              largest == n - universal;
    for (const Analysis* result : {&compact, &materialized}) {
        require(result->square_components.labels == square_labels, name, "full square partition");
        require(result->square_components.count == count, name, "square component count");
        require(result->original_components.labels == original_labels, name, "original partition");
        require(result->original_components.count == componentCount(original_labels), name,
                "original component count");
        require(result->supports == supports, name, "literal component supports");
        require(result->component_square_counts == counts, name, "per-component square counts");
        require(result->largest_support == largest, name, "largest support");
        require(result->universal_vertices == universal, name, "complete join factor size");
        require(result->cfs == expected_cfs, name, "CFS classification");
        const double expected_largest = n ? static_cast<double>(largest) / n : 0;
        const double expected_average = n && count ? static_cast<double>(support_sum) / count / n : 0;
        require(std::abs(result->largest_support_ratio - expected_largest) < 1e-12,
                name, "largest support ratio");
        require(std::abs(result->average_support_ratio - expected_average) < 1e-12,
                name, "average support ratio");
    }

    // Exercise sorted serialization on both the original graph and literal
    // square graph, including empty edge/vertex lists.
    const std::array<const Graph*, 2> serialized_graphs = {{&graph, materialized.square_graph.get()}};
    for (const Graph* output_graph : serialized_graphs) {
        std::ostringstream output;
        writeGraph(output, *output_graph);
        const auto parsed = sgb::parse_graph(output.str());
        require(parsed.vertices == boost::num_vertices(*output_graph), name, "serialized vertices");
        std::set<std::pair<std::size_t, std::size_t>> edges;
        const auto range = boost::edges(*output_graph);
        for (auto it = range.first; it != range.second; ++it) {
            auto a = boost::source(*it, *output_graph), b = boost::target(*it, *output_graph);
            if (a > b) std::swap(a, b);
            edges.insert({a, b});
        }
        require(std::vector<std::pair<std::size_t, std::size_t>>(edges.begin(), edges.end()) == parsed.edges,
                name, "serialized edges/order");
    }
}

Graph reordered(const Graph& input, bool relabel) {
    const std::size_t n = boost::num_vertices(input);
    std::vector<std::size_t> permutation(n);
    std::iota(permutation.begin(), permutation.end(), 0);
    if (relabel) {
        std::mt19937 generator(20261030);
        std::shuffle(permutation.begin(), permutation.end(), generator);
    }
    std::vector<std::pair<std::size_t, std::size_t>> edges;
    const auto range = boost::edges(input);
    for (auto it = range.first; it != range.second; ++it)
        edges.push_back({boost::source(*it, input), boost::target(*it, input)});
    Graph output(n);
    for (auto it = edges.rbegin(); it != edges.rend(); ++it)
        boost::add_edge(permutation[it->second], permutation[it->first], output);
    return output;
}

int run(const std::string& corpus) {
    std::ifstream input(corpus);
    if (!input) throw std::runtime_error("Cannot open structural test corpus: " + corpus);
    std::string line;
    std::size_t cases = 0, line_number = 0;
    while (std::getline(input, line)) {
        ++line_number;
        const auto graph = fromParsedGraph(sgb::parse_graph(line));
        require(boost::num_vertices(graph) == 100, corpus, "expected 100 vertices");
        const auto name = "corpus line " + std::to_string(line_number);
        check(graph, name);
        check(reordered(graph, false), name + " reversed edge insertion");
        check(reordered(graph, true), name + " permuted vertices/reversed edges");
        cases += 3;
    }
    require(input.eof() && line_number != 0, corpus, "missing/unreadable corpus");
    const std::vector<std::pair<std::string, std::string>> targeted = {
        {"empty", "[] []"},
        {"singleton", "[1] []"},
        {"edgeless", "[1,2,3,4] []"},
        {"induced square", "[1,2,3,4] [(1,2),(2,3),(3,4),(1,4)]"},
        {"chorded square", "[1,2,3,4] [(1,2),(2,3),(3,4),(1,4),(1,3)]"},
        {"complete", "[1,2,3,4] [(1,2),(1,3),(1,4),(2,3),(2,4),(3,4)]"},
        {"two squares sharing an edge", "[1,2,3,4,5,6] [(1,2),(2,3),(3,4),(1,4),(2,5),(5,6),(1,6)]"},
        {"three squares sharing a diagonal", "[1,2,3,4,5] [(1,3),(1,4),(1,5),(2,3),(2,4),(2,5)]"},
        {"disconnected square and isolate", "[1,2,3,4,5] [(1,2),(2,3),(3,4),(1,4)]"},
        {"square joined to complete factor", "[1,2,3,4,5,6] [(1,2),(2,3),(3,4),(1,4),(1,5),(2,5),(3,5),(4,5),(1,6),(2,6),(3,6),(4,6),(5,6)]"}
    };
    for (const auto& item : targeted) {
        check(fromParsedGraph(sgb::parse_graph(item.second)), item.first);
        ++cases;
    }
    Graph overlap(100);
    for (std::size_t a = 0; a < 8; ++a)
        for (std::size_t b = 8; b < 16; ++b) boost::add_edge(a, b, overlap);
    for (std::size_t leaf = 16; leaf < 100; ++leaf) boost::add_edge(0, leaf, overlap);
    check(overlap, "100-vertex K8,8 core with 84 pendant leaves");
    check(reordered(overlap, true), "permuted K8,8 core and leaves");
    cases += 2;
    std::cout << "PASS: " << cases << " structural analyses in both component-only and literal-graph modes; "
              << "complete square sets, edge sets, partitions, supports, CFS and serialization\n";
    return 0;
}
} // namespace structural_tests

int main(int argc, char** argv) {
    try {
        if (argc > 2) throw std::runtime_error("Usage: structure-tests [benchmark-graphs-file]");
        return structural_tests::run(argc == 2 ? argv[1] : "benchmarks/graphs.txt");
    } catch (const std::exception& error) {
        std::cerr << "Structural regression: " << error.what() << '\n';
        return 1;
    }
}
