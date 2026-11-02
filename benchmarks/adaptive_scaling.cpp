// Instrumented square-search scaling probe. Graph construction and independent
// output validation are outside the measured findSquares interval.
#define main sgb_application_main
#include "../main.cpp"
#undef main

#include <chrono>

namespace scaling_probe {
using Clock = std::chrono::steady_clock;

double seconds(Clock::time_point start, Clock::time_point end) {
    return std::chrono::duration<double>(end - start).count();
}

struct KeyHash {
    std::size_t operator()(const std::array<Vertex, 4>& key) const {
        std::size_t result = 0;
        for (Vertex item : key) result = result * 1315423911U + item;
        return result;
    }
};

const char* strategyName(SquareSearchStrategy strategy) {
    if (strategy == SquareSearchStrategy::Wedges) return "wedges";
    if (strategy == SquareSearchStrategy::MissingEdges) return "missing_edges";
    throw std::logic_error("Probe did not receive a selected strategy");
}

int run(const char* path) {
    const auto construction_start = Clock::now();
    std::ifstream input(path);
    std::size_t n;
    unsigned complement;
    if (!(input >> n >> complement) || complement > 1 ||
        (n && n > std::numeric_limits<std::size_t>::max() / n))
        throw std::runtime_error("Invalid compact graph header");
    std::vector<unsigned char> adjacency(n * n, complement ? 1 : 0);
    for (std::size_t v = 0; v < n; ++v) adjacency[v * n + v] = 0;
    std::size_t listed = 0, a, b;
    std::pair<std::size_t, std::size_t> previous;
    while (input >> a) {
        if (!(input >> b) || a >= b || b >= n ||
            (listed && std::make_pair(a, b) <= previous))
            throw std::runtime_error("Compact pairs must be sorted, unique, and satisfy 0 <= a < b < n");
        adjacency[a * n + b] = adjacency[b * n + a] = complement ? 0 : 1;
        previous = {a, b};
        ++listed;
    }
    if (!input.eof() || input.bad()) throw std::runtime_error("Malformed compact graph input");
    Graph graph(n);
    for (std::size_t u = 0; u < n; ++u)
        for (std::size_t v = u + 1; v < n; ++v)
            if (adjacency[u * n + v]) boost::add_edge(u, v, graph);
    const auto construction_end = Clock::now();

    SquareSearchMetrics metrics;
    const auto search_start = Clock::now();
    const auto squares = findSquares(graph, SquareSearchStrategy::Auto, 64 * 1024 * 1024, &metrics);
    const auto search_end = Clock::now();

    // This checks validity and uniqueness independently of the production
    // membership structure, canonicalization, search, and ordering routines.
    std::unordered_set<std::array<Vertex, 4>, KeyHash> distinct;
    for (const auto& square : squares) {
        Vertex u = square.first.first, v = square.first.second;
        Vertex x = square.second.first, y = square.second.second;
        if (u >= n || v >= n || x >= n || y >= n ||
            u == v || u == x || u == y || v == x || v == y || x == y ||
            adjacency[u * n + v] || adjacency[x * n + y] ||
            !adjacency[u * n + x] || !adjacency[u * n + y] ||
            !adjacency[v * n + x] || !adjacency[v * n + y])
            throw std::runtime_error("Search returned a non-induced square");
        if (u > v) std::swap(u, v);
        if (x > y) std::swap(x, y);
        if (std::make_pair(u, v) > std::make_pair(x, y)) {
            std::swap(u, x);
            std::swap(v, y);
        }
        const std::array<Vertex, 4> key = {{u, v, x, y}};
        if (!distinct.insert(key).second)
            throw std::runtime_error("Search returned a duplicate square");
    }
    if (metrics.squares != squares.size() || metrics.vertices != n ||
        metrics.edges != boost::num_edges(graph))
        throw std::runtime_error("Search metric totals do not match the input/output");
    const auto validation_end = Clock::now();
    std::cout << std::setprecision(17)
              << "{\"vertices\":" << n << ",\"edges\":" << boost::num_edges(graph)
              << ",\"listed_pairs\":" << listed << ",\"input_is_complement\":"
              << (complement ? "true" : "false")
              << ",\"strategy\":\"" << strategyName(metrics.strategy) << "\""
              << ",\"dense_adjacency\":" << (metrics.dense_adjacency ? "true" : "false")
              << ",\"active_vertices\":" << metrics.active_vertices
              << ",\"nonedges\":" << metrics.nonedges
              << ",\"wedge_visits\":" << metrics.wedge_visits
              << ",\"wedge_pairs\":" << metrics.wedge_pairs
              << ",\"missing_edge_pairs\":" << metrics.missing_edge_pairs
              << ",\"squares\":" << metrics.squares
              << ",\"radix_passes\":" << metrics.radix_passes
              << ",\"estimated_wedge_work\":" << metrics.estimated_wedge_work
              << ",\"estimated_missing_edge_work\":" << metrics.estimated_missing_edge_work
              << ",\"search_seconds\":" << seconds(search_start, search_end)
              << ",\"construction_seconds\":" << seconds(construction_start, construction_end)
              << ",\"validation_seconds\":" << seconds(search_end, validation_end)
              << ",\"every_square_valid_and_unique\":true}\n";
    std::cout.flush();
    if (!std::cout) throw std::runtime_error("Failed to write scaling result");
    return 0;
}
} // namespace scaling_probe

int main(int argc, char** argv) {
    try {
        if (argc != 2) throw std::runtime_error("Usage: adaptive-scaling compact-graph-file");
        return scaling_probe::run(argv[1]);
    } catch (const std::exception& error) {
        std::cerr << "Scaling probe: " << error.what() << '\n';
        return 1;
    }
}
