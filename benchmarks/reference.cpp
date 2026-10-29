// Independent C++11 reference: enumerate all four-vertex subsets in an adjacency
// matrix; an induced C4 has four edges and degree two at each of its vertices.
// Squares are adjacent exactly when they share a diagonal (a nonedge).
// No SGB source or Boost code is used. Reads graphs.txt and emits one JSON line
// per graph. Literal square support, legacy full-support CFS, and intended CFS
// allowing a complete join factor are reported separately.
#include <algorithm>
#include <array>
#include <fstream>
#include <iostream>
#include <numeric>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct DSU {
    std::vector<int> parent;
    explicit DSU(int size) : parent(size) { std::iota(parent.begin(), parent.end(), 0); }
    int root(int i) { return parent[i] == i ? i : parent[i] = root(parent[i]); }
    void join(int a, int b) { a = root(a); b = root(b); if (a != b) parent[b] = a; }
};

void analyze(const std::string& line) {
    auto close = line.find(']');
    if (close == std::string::npos) throw std::runtime_error("Missing vertex list");
    std::string labels = line.substr(1, close - 1);
    std::replace(labels.begin(), labels.end(), ',', ' ');
    std::istringstream input(labels);
    int label, n = 0;
    while (input >> label) if (label != ++n) throw std::runtime_error("Expected contiguous 1-based vertices");
    if (n != 100) throw std::runtime_error("Benchmark graph must have exactly 100 vertices");
    std::vector<std::vector<bool>> adjacency(n, std::vector<bool>(n, false));
    std::string edge_text = line.substr(close + 1);
    const std::regex edge_pattern("\\(([0-9]+),([0-9]+)\\)");
    int edge_count = 0;
    for (std::sregex_iterator it(edge_text.begin(), edge_text.end(), edge_pattern), end; it != end; ++it) {
        int a = std::stoi((*it)[1]) - 1, b = std::stoi((*it)[2]) - 1;
        if (a < 0 || a >= n || b < 0 || b >= n || a == b || adjacency[a][b])
            throw std::runtime_error("Invalid or duplicate edge");
        adjacency[a][b] = adjacency[b][a] = true;
        ++edge_count;
    }
    DSU original(n);
    for (int a = 0; a < n; ++a) for (int b = a + 1; b < n; ++b)
        if (adjacency[a][b]) original.join(a, b);
    std::set<int> original_roots;
    for (int i = 0; i < n; ++i) original_roots.insert(original.root(i));
    std::vector<int> universal;
    for (int i = 0; i < n; ++i)
        if (std::count(adjacency[i].begin(), adjacency[i].end(), true) == n - 1)
            universal.push_back(i);

    std::vector<std::array<int, 4>> squares;
    for (int a = 0; a < n; ++a) for (int b = a + 1; b < n; ++b)
    for (int c = b + 1; c < n; ++c) for (int d = c + 1; d < n; ++d) {
        int ab = adjacency[a][b], ac = adjacency[a][c], ad = adjacency[a][d];
        int bc = adjacency[b][c], bd = adjacency[b][d], cd = adjacency[c][d];
        if (ab + ac + ad == 2 && ab + bc + bd == 2 &&
            ac + bc + cd == 2 && ad + bd + cd == 2)
            squares.push_back({{a, b, c, d}});
    }

    DSU components(static_cast<int>(squares.size()));
    std::vector<std::vector<int>> previous(n, std::vector<int>(n, -1));
    for (int i = 0; i < static_cast<int>(squares.size()); ++i)
        for (int j = 0; j < 4; ++j) for (int k = j + 1; k < 4; ++k) {
            int a = squares[i][j], b = squares[i][k];
            if (!adjacency[a][b]) {
                if (previous[a][b] >= 0) components.join(i, previous[a][b]);
                previous[a][b] = i;
            }
        }
    std::vector<std::set<int>> support(squares.size());
    std::vector<int> counts(squares.size(), 0);
    for (int i = 0; i < static_cast<int>(squares.size()); ++i) {
        int root = components.root(i);
        ++counts[root];
        support[root].insert(squares[i].begin(), squares[i].end());
    }
    std::vector<std::pair<int, int>> summary;
    int largest = 0, support_sum = 0;
    bool intended_cfs = false;
    for (int i = 0; i < static_cast<int>(squares.size()); ++i) if (counts[i]) {
        int size = static_cast<int>(support[i].size());
        largest = std::max(largest, size);
        support_sum += size;
        summary.push_back(std::make_pair(size, counts[i]));
        // A universal vertex cannot belong to an induced C4. Its clique factor
        // is excluded only from the CFS target, never inserted into support.
        if (size == n - static_cast<int>(universal.size())) intended_cfs = true;
    }
    std::sort(summary.rbegin(), summary.rend());
    std::cout << "{\"vertices\":" << n << ",\"edges\":" << edge_count
              << ",\"original_components\":" << original_roots.size()
              << ",\"squares\":" << squares.size() << ",\"components\":" << summary.size()
              << ",\"largest_support\":" << largest << ",\"support_sum\":" << support_sum
              << ",\"universal_vertices\":" << universal.size()
              << ",\"legacy_cfs\":" << (largest == n ? "true" : "false")
              << ",\"intended_cfs\":" << (universal.size() == static_cast<size_t>(n) ? "null" : intended_cfs ? "true" : "false")
              << ",\"component_details\":[";
    for (size_t i = 0; i < summary.size(); ++i) {
        if (i) std::cout << ',';
        std::cout << "{\"support\":" << summary[i].first << ",\"squares\":" << summary[i].second << '}';
    }
    std::cout << "]}\n";
}

int main(int argc, char** argv) {
    if (argc != 2) { std::cerr << "Usage: reference graphs.txt\n"; return 2; }
    std::ifstream input(argv[1]);
    if (!input) { std::cerr << "Cannot open input\n"; return 2; }
    try {
        std::string line;
        while (std::getline(input, line)) analyze(line);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
