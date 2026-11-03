#ifndef SGB_INPUT_H
#define SGB_INPUT_H

#include <cctype>
#include <cstddef>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace sgb {

struct ParsedGraph {
    std::size_t vertices = 0;
    std::vector<std::pair<std::size_t, std::size_t>> edges;
};

namespace input_detail {

class GraphParser {
public:
    explicit GraphParser(const std::string& text) : text_(text), position_(0) {}

    ParsedGraph parse() {
        ParsedGraph graph;
        std::size_t base = 0;
        expect('[');
        if (!take(']')) {
            base = number();
            if (base > 1)
                fail("Vertex labels must start at zero or one");
            graph.vertices = 1;
            while (take(',')) {
                const std::size_t label = number();
                if (graph.vertices > std::numeric_limits<std::size_t>::max() - base ||
                    label != base + graph.vertices)
                    fail("Vertex labels must be contiguous and in ascending order");
                if (graph.vertices == std::numeric_limits<std::size_t>::max())
                    fail("Too many vertices");
                ++graph.vertices;
            }
            expect(']');
        }
        expect('[');
        std::set<std::pair<std::size_t, std::size_t>> edges;
        if (!take(']')) {
            do {
                expect('(');
                const std::size_t first = number();
                expect(',');
                const std::size_t second = number();
                expect(')');
                if (first < base || second < base || first - base >= graph.vertices ||
                    second - base >= graph.vertices)
                    fail("Edge endpoint is not in the declared vertex list");
                // The archived exporter appended (1,1). Interpret inputs as
                // simple undirected graphs: ignore loops and deduplicate edges.
                if (first != second) {
                    const std::size_t a = first - base;
                    const std::size_t b = second - base;
                    edges.insert(a < b ? std::make_pair(a, b) : std::make_pair(b, a));
                }
            } while (take(','));
            expect(']');
        }
        skip_space();
        if (position_ != text_.size())
            fail("Unexpected text after the edge list");
        graph.edges.assign(edges.begin(), edges.end());
        return graph;
    }

private:
    const std::string& text_;
    std::size_t position_;

    void skip_space() {
        while (position_ < text_.size() &&
               std::isspace(static_cast<unsigned char>(text_[position_])))
            ++position_;
    }

    bool take(char expected) {
        skip_space();
        if (position_ < text_.size() && text_[position_] == expected) {
            ++position_;
            return true;
        }
        return false;
    }

    void expect(char expected) {
        if (!take(expected))
            fail(std::string("Expected '") + expected + "'");
    }

    std::size_t number() {
        skip_space();
        if (position_ == text_.size() || text_[position_] < '0' || text_[position_] > '9')
            fail("Expected a nonnegative integer vertex label");
        std::size_t value = 0;
        while (position_ < text_.size() && text_[position_] >= '0' && text_[position_] <= '9') {
            const unsigned digit = static_cast<unsigned>(text_[position_] - '0');
            if (value > (std::numeric_limits<std::size_t>::max() - digit) / 10)
                fail("Vertex label is too large");
            value = value * 10 + digit;
            ++position_;
        }
        return value;
    }

    void fail(const std::string& message) const {
        throw std::invalid_argument(message + " at column " + std::to_string(position_ + 1));
    }
};

} // namespace input_detail

inline ParsedGraph parse_graph(const std::string& line) {
    return input_detail::GraphParser(line).parse();
}

} // namespace sgb

#endif // SGB_INPUT_H
