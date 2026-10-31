// Independent checker for selected large graph benchmarks (no Boost/SGB code).
// Intersect bitset neighborhoods for each nonedge. Each nonadjacent pair in
// that intersection completes a square. Order its two diagonals to emit it
// exactly once. A square joins its two diagonal nodes; connected components
// of this incidence representation give the literal square components.
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace large_reference {
using Vertex = std::uint32_t;
using Edge = std::pair<Vertex, Vertex>;
const Vertex missing = std::numeric_limits<Vertex>::max();

struct ParsedGraph {
    std::size_t vertices = 0;
    std::vector<Edge> edges;
};

// This standalone parser accepts the generated one-based simple-graph format.
// Unlike SGB's general input compatibility rules, loops and duplicates are
// errors here: generated benchmark inputs should contain neither.
class Parser {
    const std::string& text;
    std::size_t position = 0;

    void whitespace() {
        while (position < text.size() && std::isspace(static_cast<unsigned char>(text[position])))
            ++position;
    }

    [[noreturn]] void fail(const std::string& message) const {
        throw std::runtime_error("column " + std::to_string(position + 1) + ": " + message);
    }

    bool take(char character) {
        whitespace();
        if (position < text.size() && text[position] == character) {
            ++position;
            return true;
        }
        return false;
    }

    void expect(char character) {
        if (!take(character)) fail(std::string("expected '") + character + "'");
    }

    Vertex number() {
        whitespace();
        if (position == text.size() || text[position] < '0' || text[position] > '9')
            fail("expected a nonnegative decimal integer");
        Vertex result = 0;
        while (position < text.size() && text[position] >= '0' && text[position] <= '9') {
            const Vertex digit = static_cast<Vertex>(text[position] - '0');
            if (result > (missing - digit) / 10) fail("integer overflow");
            result = 10 * result + digit;
            ++position;
        }
        return result;
    }

public:
    explicit Parser(const std::string& value) : text(value) {}

    ParsedGraph parse() {
        ParsedGraph result;
        expect('[');
        if (!take(']')) {
            do {
                const Vertex label = number();
                if (result.vertices == missing || label != result.vertices + 1)
                    fail("vertices must be consecutive labels starting at one");
                ++result.vertices;
            } while (take(','));
            expect(']');
        }
        expect('[');
        std::set<Edge> seen;
        if (!take(']')) {
            do {
                expect('(');
                const Vertex first = number();
                expect(',');
                const Vertex second = number();
                expect(')');
                if (!first || !second || first > result.vertices || second > result.vertices)
                    fail("edge endpoint outside the vertex list");
                if (first == second) fail("self-loop in generated input");
                const Edge edge = std::minmax(first - 1, second - 1);
                if (!seen.insert(edge).second) fail("duplicate undirected edge in generated input");
                result.edges.push_back(edge);
            } while (take(','));
            expect(']');
        }
        whitespace();
        if (position != text.size()) fail("trailing text");
        return result;
    }
};

std::size_t checkedProduct(std::size_t a, std::size_t b) {
    if (b && a > std::numeric_limits<std::size_t>::max() / b)
        throw std::length_error("reference storage size overflow");
    return a * b;
}

std::size_t pairCount(std::size_t n) {
    return n == 0 ? 0 : n % 2
        ? checkedProduct(n, (n - 1) / 2) : checkedProduct(n / 2, n - 1);
}

class Matrix {
    std::size_t n, words;
    std::vector<std::uint64_t> bits;
public:
    explicit Matrix(std::size_t vertices)
        : n(vertices), words(vertices / 64 + (vertices % 64 != 0)),
          bits(checkedProduct(vertices, words), 0) {}

    void add(Vertex a, Vertex b) {
        bits[static_cast<std::size_t>(a) * words + b / 64] |= std::uint64_t(1) << (b % 64);
        bits[static_cast<std::size_t>(b) * words + a / 64] |= std::uint64_t(1) << (a % 64);
    }

    bool edge(Vertex a, Vertex b) const {
        return bits[static_cast<std::size_t>(a) * words + b / 64] & (std::uint64_t(1) << (b % 64));
    }

    void commonNeighbors(Vertex a, Vertex b, std::vector<Vertex>& output) const {
        output.clear();
        for (std::size_t word = 0; word < words; ++word) {
            std::uint64_t shared = bits[static_cast<std::size_t>(a) * words + word] &
                                   bits[static_cast<std::size_t>(b) * words + word];
            while (shared) {
                const unsigned bit = static_cast<unsigned>(__builtin_ctzll(shared));
                const std::size_t vertex = word * 64 + bit;
                if (vertex >= n) throw std::logic_error("reference bitset padding became nonzero");
                output.push_back(static_cast<Vertex>(vertex));
                shared &= shared - 1;
            }
        }
    }
};

class DiagonalComponents {
    std::size_t n;
    std::vector<Vertex> diagonal_nodes, parent, sizes;
public:
    explicit DiagonalComponents(std::size_t vertices) : n(vertices) {
        diagonal_nodes.assign(pairCount(n), missing);
    }

    Vertex node(Vertex a, Vertex b) {
        // All calls use a < b. This triangular index assigns every unordered
        // vertex pair its own slot without a hash table or square identifiers.
        if (a >= b || b >= n) throw std::logic_error("invalid reference diagonal");
        const std::size_t preceding = diagonal_nodes.size() - pairCount(n - a);
        const std::size_t slot = preceding + b - a - 1;
        Vertex& id = diagonal_nodes.at(slot);
        if (id == missing) {
            if (parent.size() == missing) throw std::length_error("too many reference diagonal nodes");
            id = static_cast<Vertex>(parent.size());
            parent.push_back(id);
            sizes.push_back(1);
        }
        return id;
    }

    Vertex root(Vertex node) {
        Vertex representative = node;
        while (parent[representative] != representative) representative = parent[representative];
        while (parent[node] != node) {
            const Vertex next = parent[node];
            parent[node] = representative;
            node = next;
        }
        return representative;
    }

    void join(Vertex a, Vertex b) {
        a = root(a);
        b = root(b);
        if (a == b) return;
        if (sizes[a] < sizes[b]) std::swap(a, b);
        parent[b] = a;
        sizes[a] += sizes[b];
    }
};

struct Square {
    Vertex diagonal_node, a, b, c, d;
};

struct Summary {
    std::size_t squares = 0;
    std::set<Vertex> support;
};

void analyze(const ParsedGraph& graph) {
    const std::size_t n = graph.vertices;
    Matrix matrix(n);
    std::vector<std::vector<Vertex>> neighbors(n);
    for (const auto& edge : graph.edges) {
        matrix.add(edge.first, edge.second);
        neighbors[edge.first].push_back(edge.second);
        neighbors[edge.second].push_back(edge.first);
    }
    std::size_t original_components = 0, universal = 0;
    std::vector<bool> visited(n, false);
    std::vector<Vertex> pending;
    for (std::size_t start = 0; start < n; ++start) {
        if (neighbors[start].size() == n - 1) ++universal;
        if (visited[start]) continue;
        ++original_components;
        visited[start] = true;
        pending.push_back(static_cast<Vertex>(start));
        while (!pending.empty()) {
            const Vertex current = pending.back();
            pending.pop_back();
            for (Vertex next : neighbors[current]) {
                if (visited[next]) continue;
                visited[next] = true;
                pending.push_back(next);
            }
        }
    }

    DiagonalComponents components(n);
    std::vector<Square> squares;
    std::vector<Vertex> common;
    for (std::size_t a = 0; a < n; ++a)
        for (std::size_t b = a + 1; b < n; ++b) {
            if (matrix.edge(static_cast<Vertex>(a), static_cast<Vertex>(b))) continue;
            matrix.commonNeighbors(static_cast<Vertex>(a), static_cast<Vertex>(b), common);
            for (std::size_t i = 0; i < common.size(); ++i)
                for (std::size_t j = i + 1; j < common.size(); ++j) {
                    const Vertex c = common[i], d = common[j];
                    if (matrix.edge(c, d) || Edge(static_cast<Vertex>(a), static_cast<Vertex>(b)) >= Edge(c, d))
                        continue;
                    const Vertex first = components.node(static_cast<Vertex>(a), static_cast<Vertex>(b));
                    const Vertex second = components.node(c, d);
                    components.join(first, second);
                    squares.push_back({first, static_cast<Vertex>(a), static_cast<Vertex>(b), c, d});
                }
        }

    // Every diagonal node was introduced by an actual square. A component of
    // diagonal nodes therefore corresponds to exactly one nonempty component
    // of squares sharing diagonals. Never add universal vertices to support.
    std::map<Vertex, Summary> groups;
    for (const auto& square : squares) {
        auto& group = groups[components.root(square.diagonal_node)];
        ++group.squares;
        group.support.insert(square.a);
        group.support.insert(square.b);
        group.support.insert(square.c);
        group.support.insert(square.d);
    }
    std::size_t largest = 0, support_sum = 0;
    std::vector<std::pair<std::size_t, std::size_t>> details;
    for (const auto& entry : groups) {
        const auto& group = entry.second;
        largest = std::max(largest, group.support.size());
        support_sum += group.support.size();
        details.push_back({group.support.size(), group.squares});
    }
    std::sort(details.rbegin(), details.rend());
    const bool eligible = original_components == 1 && !squares.empty();
    const bool legacy = eligible && largest == n;
    const bool intended = eligible && largest == n - universal;
    std::cout << "{\"vertices\":" << n << ",\"edges\":" << graph.edges.size()
              << ",\"original_components\":" << original_components
              << ",\"squares\":" << squares.size() << ",\"components\":" << groups.size()
              << ",\"largest_support\":" << largest << ",\"support_sum\":" << support_sum
              << ",\"universal_vertices\":" << universal
              << ",\"legacy_cfs\":" << (legacy ? "true" : "false")
              << ",\"intended_cfs\":" << (intended ? "true" : "false")
              << ",\"component_details\":[";
    for (std::size_t i = 0; i < details.size(); ++i) {
        if (i) std::cout << ',';
        std::cout << "{\"support\":" << details[i].first << ",\"squares\":" << details[i].second << '}';
    }
    std::cout << "]}\n";
}
} // namespace large_reference

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "Usage: reference-large graph-file\n";
        return 2;
    }
    std::ifstream input(argv[1]);
    if (!input) {
        std::cerr << "Cannot open reference graph file: " << argv[1] << '\n';
        return 2;
    }
    try {
        std::size_t line_number = 0;
        std::string line;
        while (std::getline(input, line)) {
            ++line_number;
            try {
                large_reference::analyze(large_reference::Parser(line).parse());
            } catch (const std::exception& error) {
                throw std::runtime_error(std::string(argv[1]) + ':' + std::to_string(line_number) + ": " + error.what());
            }
        }
        if (!input.eof() || input.bad()) throw std::runtime_error("Failed to read reference input");
        if (!line_number) throw std::runtime_error("Reference input contains no graphs");
        std::cout.flush();
        if (!std::cout) throw std::runtime_error("Failed to write reference output");
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
