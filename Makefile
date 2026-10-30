CXX ?= c++
CPPFLAGS ?=
CXXFLAGS ?= -O2
LDFLAGS ?=
LDLIBS ?=
PYTHON ?= python3
WARNINGS = -Wall -Wextra -Wpedantic -Werror
SANITIZER_FLAGS ?= -fsanitize=address,undefined -fno-omit-frame-pointer

.PHONY: all check bench sanitize check-sanitize clean

all: build/SGB

build:
	mkdir -p $@

build/SGB: main.cpp flags.h input.h | build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -std=c++11 $(WARNINGS) $(LDFLAGS) main.cpp -o $@ $(LDLIBS)

build/sgb-reference: benchmarks/reference.cpp | build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -std=c++11 $(WARNINGS) $(LDFLAGS) $< -o $@ $(LDLIBS)

build/SGB-sanitize: main.cpp flags.h input.h | build
	$(CXX) $(CPPFLAGS) -std=c++11 -O1 -g $(WARNINGS) $(SANITIZER_FLAGS) $(LDFLAGS) main.cpp -o $@ $(LDLIBS)

build/structure-tests: tests/structure.cpp main.cpp flags.h input.h | build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -std=c++11 $(WARNINGS) $(LDFLAGS) $< -o $@ $(LDLIBS)

build/structure-tests-sanitize: tests/structure.cpp main.cpp flags.h input.h | build
	$(CXX) $(CPPFLAGS) -std=c++11 -O1 -g $(WARNINGS) $(SANITIZER_FLAGS) $(LDFLAGS) $< -o $@ $(LDLIBS)

check: build/SGB build/sgb-reference build/structure-tests
	$(PYTHON) benchmarks/test_runner.py
	$(PYTHON) benchmarks/test_performance.py
	$(PYTHON) tests/regression.py --binary build/SGB
	./build/structure-tests benchmarks/graphs.txt
	$(PYTHON) benchmarks/run.py --sgb build/SGB --reference build/sgb-reference --output build/benchmark-results.json

bench: build/SGB build/sgb-reference
	$(PYTHON) benchmarks/run.py --sgb build/SGB --reference build/sgb-reference --output build/benchmark-results.json

sanitize: check-sanitize

check-sanitize: build/SGB-sanitize build/sgb-reference build/structure-tests-sanitize
	$(PYTHON) benchmarks/test_runner.py
	$(PYTHON) benchmarks/test_performance.py
	$(PYTHON) tests/regression.py --binary build/SGB-sanitize
	ASAN_OPTIONS=$${ASAN_OPTIONS:-detect_leaks=0} UBSAN_OPTIONS=$${UBSAN_OPTIONS:-halt_on_error=1:print_stacktrace=1} ./build/structure-tests-sanitize benchmarks/graphs.txt
	ASAN_OPTIONS=$${ASAN_OPTIONS:-detect_leaks=0} UBSAN_OPTIONS=$${UBSAN_OPTIONS:-halt_on_error=1:print_stacktrace=1} $(PYTHON) benchmarks/run.py --sgb build/SGB-sanitize --reference build/sgb-reference --output build/benchmark-results-sanitize.json

clean:
	rm -rf build
