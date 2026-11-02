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

// Preserve the pre-adaptive discovery order independently of the new search.
// The four-subset oracle below establishes the mathematical square set; this
// older neighbor walk checks the user-visible labels and diagonal orientation.
std::vector<Square> legacyOrder(const Graph& graph) {
    std::vector<Square> squares;
    std::set<Key> seen;
    const auto vertices = boost::vertices(graph);
    for (auto v = vertices.first; v != vertices.second; ++v) {
        const auto neighbors = boost::adjacent_vertices(*v, graph);
        for (auto a = neighbors.first; a != neighbors.second; ++a) {
            auto b = a;
            for (++b; b != neighbors.second; ++b) {
                if (*a == *b || boost::edge(*a, *b, graph).second) continue;
                const auto across = boost::adjacent_vertices(*b, graph);
                for (auto opposite = across.first; opposite != across.second; ++opposite) {
                    if (*opposite == *v || boost::edge(*opposite, *v, graph).second) continue;
                    if (!boost::edge(*a, *opposite, graph).second) continue;
                    if (seen.insert(key(*v, *opposite, *a, *b)).second)
                        squares.push_back({{*v, *opposite}, {*a, *b}});
                }
            }
        }
    }
    return squares;
}

void requireOrderedSquares(const std::vector<Square>& actual,
                           const std::vector<Square>& expected,
                           const std::string& name) {
    require(actual.size() == expected.size(), name, "legacy square count");
    for (std::size_t i = 0; i < expected.size(); ++i)
        require(actual[i].first == expected[i].first && actual[i].second == expected[i].second,
                name, "legacy discovery order and diagonal orientation at square " + std::to_string(i));
}

std::size_t forced_search_checks = 0;

void checkSearchStrategies(const Graph& graph, const std::string& name,
                           bool include_missing_edge_search = true) {
    const auto expected = legacyOrder(graph);
    std::vector<SquareSearchStrategy> strategies{SquareSearchStrategy::Wedges};
    if (include_missing_edge_search) strategies.push_back(SquareSearchStrategy::MissingEdges);
    for (auto strategy : strategies) {
        for (std::size_t budget : {std::size_t(0), std::size_t(64 * 1024 * 1024)}) {
            SquareSearchMetrics metrics{};
            const auto actual = findSquares(graph, strategy, budget, &metrics);
            requireOrderedSquares(actual, expected, name + " forced search");
            require(metrics.strategy == strategy, name, "forced search strategy was not honored");
            require(metrics.vertices == boost::num_vertices(graph), name, "search metric vertex count");
            require(metrics.squares == expected.size(), name, "search metric square count");
            if (boost::num_vertices(graph) != 0 && budget == 0)
                require(!metrics.dense_adjacency, name, "zero budget did not force sparse adjacency");
            if (!expected.empty() && budget != 0)
                require(metrics.dense_adjacency, name, "word-boundary checks did not exercise the bit matrix");
            ++forced_search_checks;
        }
    }
}

void check(const Graph& graph, const std::string& name) {
    const auto compact = analyze(graph, SquareGraphMode::ComponentsOnly);
    const auto materialized = analyze(graph, SquareGraphMode::Materialize);
    const auto legacy_squares = legacyOrder(graph);
    requireOrderedSquares(compact.squares, legacy_squares, name);
    requireOrderedSquares(materialized.squares, legacy_squares, name + " materialized");
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
        if (line_number == 1 || line_number == 6 || line_number == 9 || line_number == 12)
            checkSearchStrategies(graph, name);
        if (line_number == 1 || line_number == 12)
            checkSearchStrategies(reordered(graph, true), name + " permuted forced paths");
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
        {"normalized square joined to complete factor", "[1,2,3,4,5] [(1,2),(2,1),(2,3),(3,4),(1,4),(1,5),(2,5),(3,5),(4,5),(5,5)]"},
        {"square joined to complete factor", "[1,2,3,4,5,6] [(1,2),(2,3),(3,4),(1,4),(1,5),(2,5),(3,5),(4,5),(1,6),(2,6),(3,6),(4,6),(5,6)]"}
    };
    for (const auto& item : targeted) {
        const auto graph = fromParsedGraph(sgb::parse_graph(item.second));
        check(graph, item.first);
        checkSearchStrategies(graph, item.first);
        ++cases;
    }
    Graph overlap(100);
    for (std::size_t a = 0; a < 8; ++a)
        for (std::size_t b = 8; b < 16; ++b) boost::add_edge(a, b, overlap);
    for (std::size_t leaf = 16; leaf < 100; ++leaf) boost::add_edge(0, leaf, overlap);
    check(overlap, "100-vertex K8,8 core with 84 pendant leaves");
    check(reordered(overlap, true), "permuted K8,8 core and leaves");
    cases += 2;

    // Squares whose vertex indices cross machine-word boundaries catch bit
    // addressing/padding errors without requiring a large square graph.
    for (std::size_t n : {63u, 64u, 65u, 127u, 128u, 129u}) {
        Graph boundary(n);
        const Vertex a = 0, b = n / 2, c = n - 2, d = n - 1;
        boost::add_edge(a, b, boundary);
        boost::add_edge(b, c, boundary);
        boost::add_edge(c, d, boundary);
        boost::add_edge(d, a, boundary);
        // A pendant edge exercises degree differences without creating a
        // second cycle or hiding the boundary-crossing square behind chords.
        boost::add_edge(a, 1, boundary);
        check(boundary, "word boundary n=" + std::to_string(n));
        if (n == 63 || n == 65 || n == 129)
            checkSearchStrategies(boundary, "forced word boundary n=" + std::to_string(n));
        ++cases;
    }

    // A dense complement-matching family has exactly C(k,2) squares for k
    // missing matching edges, and exercises universal vertices in the same
    // graph. Full edge-set checking remains small despite n=100.
    for (std::size_t missing_pairs : {0u, 1u, 2u, 8u}) {
        Graph dense(100);
        for (Vertex a = 0; a < 100; ++a)
            for (Vertex b = a + 1; b < 100; ++b)
                if (!(a < 2 * missing_pairs && a % 2 == 0 && b == a + 1))
                    boost::add_edge(a, b, dense);
        check(dense, "100-vertex complement matching k=" + std::to_string(missing_pairs));
        check(reordered(dense, true), "permuted 100-vertex complement matching k=" +
                                     std::to_string(missing_pairs));
        checkSearchStrategies(reordered(dense, true), "forced complement matching k=" +
                                                     std::to_string(missing_pairs));
        cases += 2;
    }

    Graph star(100), complement_star(100);
    for (Vertex a = 0; a < 100; ++a)
        for (Vertex b = a + 1; b < 100; ++b) {
            if (a == 0) boost::add_edge(a, b, star);
            if (!(a == 0 && b < 20)) boost::add_edge(a, b, complement_star);
        }
    check(star, "100-vertex star with no squares");
    check(reordered(star, true), "permuted 100-vertex star with no squares");
    check(complement_star, "100-vertex complement star with no squares");
    checkSearchStrategies(star, "forced 100-vertex star");
    checkSearchStrategies(complement_star, "forced 100-vertex complement star");
    cases += 3;

    // Exercise ordering keys above 255 with analytically known small square
    // sets. A full four-subset scan at this size adds little coverage, while a
    // forced missing-edge-pair search would inspect hundreds of millions of
    // irrelevant pairs in these deliberately sparse examples.
    Graph rank_boundary(264);
    boost::add_edge(0, 2, rank_boundary);
    for (Vertex v = 3; v < 264; ++v) boost::add_edge(1, v, rank_boundary);
    boost::add_edge(0, 1, rank_boundary);
    boost::add_edge(2, 258, rank_boundary);
    boost::add_edge(2, 259, rank_boundary);
    // The K2,3 core has three squares; opposite vertices 258 and 259 have
    // positions 255 and 256 in vertex1's original neighbor insertion order.
    require(legacyOrder(rank_boundary).size() == 3, "rank boundary", "K2,3 square count");
    checkSearchStrategies(rank_boundary, "neighbor ranks straddling 255/256", false);

    Graph vertex_boundary(264);
    for (const auto& cycle : std::vector<std::array<Vertex, 4>>{{{1, 3, 4, 6}}, {{256, 258, 260, 263}}})
        for (std::size_t i = 0; i < 4; ++i)
            boost::add_edge(cycle[i], cycle[(i + 1) % 4], vertex_boundary);
    require(legacyOrder(vertex_boundary).size() == 2, "vertex boundary", "disjoint C4 count");
    checkSearchStrategies(vertex_boundary, "minimum vertex straddling 255/256", false);
    std::cout << "PASS: " << cases << " structural analyses in both component-only and literal-graph modes; "
              << forced_search_checks << " forced strategy/adjacency checks; complete square sets, "
              << "legacy order/orientation, edge sets, partitions, supports, CFS and serialization\n";
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
