#ifndef SGB_FLAGS_H
#define SGB_FLAGS_H

#include <cerrno>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace sgb {

struct Options {
    bool verbose = false;
    bool full = false;
    bool debug = false;
    bool export_graphs = false;
    bool file_mode = false;
    bool alpha_mode = false;
    bool small_world = false;
    bool help = false;
    std::size_t vertices = 0;
    std::size_t trials = 1;
    std::size_t mean_degree = 0;
    double probability = 0.0;
    double alpha = 0.0;
    bool has_seed = false;
    std::uint64_t seed = 0;
    std::string input_path;
};

inline std::string usage() {
    return
        "Usage:\n"
        "  SGB [flags] vertices probability trials [--seed N]\n"
        "  SGB -a [flags] vertices alpha trials [--seed N]\n"
        "  SGB -s [flags] vertices probability trials mean_degree [--seed N]\n"
        "  SGB -t [flags] input_file\n"
        "Flags: -v verbose, -d debug, -f per-graph CSV, -e export, -h help.\n"
        "Short flags may be combined (for example -tv). Use -- before a filename\n"
        "beginning with '-'. Small-world degree must be even, except n-1 is\n"
        "allowed for the complete graph. Degree zero is allowed.\n";
}

namespace options_detail {

inline std::uint64_t unsigned_number(const std::string& text, const char* name) {
    if (text.empty())
        throw std::invalid_argument(std::string(name) + " must be a nonnegative integer");
    std::size_t index = text[0] == '+' ? 1 : 0;
    if (index == text.size())
        throw std::invalid_argument(std::string(name) + " must be a nonnegative integer");
    std::uint64_t value = 0;
    for (; index < text.size(); ++index) {
        const char c = text[index];
        if (c < '0' || c > '9')
            throw std::invalid_argument(std::string(name) + " must be a nonnegative integer");
        const unsigned digit = static_cast<unsigned>(c - '0');
        if (value > (std::numeric_limits<std::uint64_t>::max() - digit) / 10)
            throw std::invalid_argument(std::string(name) + " is too large");
        value = value * 10 + digit;
    }
    return value;
}

inline std::size_t count(const std::string& text, const char* name, bool allow_zero) {
    const std::uint64_t value = unsigned_number(text, name);
    if (value > std::numeric_limits<std::size_t>::max())
        throw std::invalid_argument(std::string(name) + " is too large");
    if (!allow_zero && value == 0)
        throw std::invalid_argument(std::string(name) + " must be greater than zero");
    return static_cast<std::size_t>(value);
}

inline double real_number(const std::string& text, const char* name) {
    // Reject whitespace so a quoted partial argument cannot be accepted.
    if (text.empty() || text.find_first_of(" \t\r\n\v\f") != std::string::npos)
        throw std::invalid_argument(std::string(name) + " must be a finite number");
    char* end = NULL;
    errno = 0;
    const double value = std::strtod(text.c_str(), &end);
    if (end == text.c_str() || *end != '\0' || errno == ERANGE || !std::isfinite(value))
        throw std::invalid_argument(std::string(name) + " must be a finite number");
    return value;
}

} // namespace options_detail

inline Options parse_options(int argc, const char* const argv[]) {
    Options options;
    std::vector<std::string> positional;
    bool end_options = false;
    for (int i = 1; i < argc; ++i) {
        if (argv == NULL || argv[i] == NULL)
            throw std::invalid_argument("Missing command-line argument");
        const std::string argument(argv[i]);
        if (!end_options && argument == "--") {
            end_options = true;
        } else if (!end_options && argument == "--help") {
            options.help = true;
        } else if (!end_options && (argument == "--seed" || argument.compare(0, 7, "--seed=") == 0)) {
            if (options.has_seed)
                throw std::invalid_argument("--seed may only be specified once");
            std::string value;
            if (argument == "--seed") {
                if (i + 1 >= argc || argv[i + 1] == NULL)
                    throw std::invalid_argument("--seed requires a nonnegative integer");
                value = argv[++i];
            } else {
                value = argument.substr(7);
            }
            options.seed = options_detail::unsigned_number(value, "Seed");
            options.has_seed = true;
        } else if (!end_options && argument.size() > 1 && argument[0] == '-' &&
                   !(argument[1] >= '0' && argument[1] <= '9') && argument[1] != '.') {
            for (std::size_t j = 1; j < argument.size(); ++j) {
                switch (argument[j]) {
                    case 'v': options.verbose = true; break;
                    case 'f': options.full = true; break;
                    case 'd': options.debug = true; break;
                    case 't': options.file_mode = true; break;
                    case 'a': options.alpha_mode = true; break;
                    case 's': options.small_world = true; break;
                    case 'e': options.export_graphs = true; break;
                    case 'h': options.help = true; break;
                    default: throw std::invalid_argument("Unrecognized option: " + argument);
                }
            }
        } else {
            positional.push_back(argument);
        }
    }
    if (options.help)
        return options;
    if ((options.file_mode && (options.alpha_mode || options.small_world)) ||
        (options.alpha_mode && options.small_world))
        throw std::invalid_argument("File, alpha, and small-world modes cannot be combined");
    if (options.file_mode) {
        if (positional.size() != 1)
            throw std::invalid_argument("File mode requires exactly one input file");
        if (options.has_seed)
            throw std::invalid_argument("--seed is only available for random graph modes");
        options.input_path = positional[0];
        if (options.input_path.empty())
            throw std::invalid_argument("Input filename must not be empty");
        return options;
    }
    const std::size_t expected = options.small_world ? 4 : 3;
    if (positional.size() != expected)
        throw std::invalid_argument(options.small_world
            ? "Small-world mode requires vertices, probability, trials, and mean degree"
            : "Random graph mode requires vertices, probability (or alpha), and trials");
    options.vertices = options_detail::count(positional[0], "Vertex count", false);
    options.trials = options_detail::count(positional[2], "Trial count", false);
    const double parameter = options_detail::real_number(positional[1],
                                                        options.alpha_mode ? "Alpha" : "Probability");
    if (parameter < 0.0)
        throw std::invalid_argument(options.alpha_mode ? "Alpha must be nonnegative" : "Probability must be between zero and one");
    const double root_n = std::sqrt(static_cast<double>(options.vertices));
    options.probability = options.alpha_mode ? parameter / root_n : parameter;
    if (!std::isfinite(options.probability) || options.probability > 1.0)
        throw std::invalid_argument("Effective probability must be between zero and one");
    options.alpha = options.alpha_mode ? parameter : parameter * root_n;
    if (options.small_world) {
        options.mean_degree = options_detail::count(positional[3], "Mean degree", true);
        if (options.mean_degree >= options.vertices)
            throw std::invalid_argument("Mean degree must be less than the vertex count");
        if (options.mean_degree != options.vertices - 1 && options.mean_degree % 2 != 0)
            throw std::invalid_argument("Small-world mean degree must be even, unless it is n-1");
    }
    return options;
}

} // namespace sgb

#endif // SGB_FLAGS_H
