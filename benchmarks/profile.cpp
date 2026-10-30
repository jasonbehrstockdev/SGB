// Phase probe, compiled against either preserved baseline or current main.cpp.
// Timings exclude parsing, support accumulation, classification, serialization,
// and destruction after the timed phase. Use performance.py for end-to-end work.
#ifndef SGB_SOURCE
#define SGB_SOURCE "../main.cpp"
#endif
#define main sgb_application_main
#include SGB_SOURCE
#undef main

#include <chrono>

int main(int argc, char** argv) {
    try {
        if (argc != 3)
            throw std::runtime_error("Usage: profile graph-file repetitions");
        const std::uint64_t repeats = sgb::options_detail::unsigned_number(argv[2], "Repetitions");
        if (!repeats)
            throw std::runtime_error("Repetitions must be positive");
        std::ifstream input(argv[1]);
        if (!input)
            throw std::runtime_error("Cannot read graph file");
        using Clock = std::chrono::steady_clock;
        using Seconds = std::chrono::duration<double>;
        std::string line;
        std::size_t case_number = 0;
        std::cout << std::setprecision(12);
        while (std::getline(input, line)) {
            const Graph graph = fromParsedGraph(sgb::parse_graph(line));
            for (std::uint64_t repeat = 0; repeat < repeats; ++repeat) {
                const auto start = Clock::now();
                const auto squares = findSquares(graph);
                const auto enumerated = Clock::now();
#ifdef SGB_OPTIMIZED
                const auto index = indexSquares(squares);
                const auto components = findSquareComponents(squares.size(), index);
#else
                const Graph square_graph = buildSquareGraph(squares);
                const auto components = findComponents(square_graph);
#endif
                const auto connected = Clock::now();
                std::cout << "{\"case\":" << case_number << ",\"repeat\":" << repeat
                          << ",\"squares\":" << squares.size()
                          << ",\"components\":" << components.count
                          << ",\"enumeration_seconds\":" << Seconds(enumerated - start).count()
                          << ",\"connectivity_seconds\":" << Seconds(connected - enumerated).count()
                          << "}\n";
            }
            ++case_number;
        }
        if (input.bad() || (!input.eof() && input.fail()))
            throw std::runtime_error("Graph file read failed");
        if (case_number == 0)
            throw std::runtime_error("Graph file contains no records");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
