#include <assert.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#define START_FLOAT 1.0f
#define END_FLOAT 1.00001f
#define FLOATS_BETWEEN_BUG 20
#define FLOATS_BETWEEN_MAX 84

int main(int argc, char** argv) {
  fprintf(stderr, "[count.c] enter main 1\n");
  // The program counts all floats between start (inclusive) and end (exclusive)
  float start;
  float end;

  if (argc != 3) {
    fprintf(stderr, "[count.c] enter main 2\n");
    printf("Usage: %s <float1> <float2>\n", argv[0]);
    return 1;
    // fprintf(stderr, "[count.c] exit main 2\n");
  }
  // fprintf(stderr, "[count.c] exit main 1\n");
  
  fprintf(stderr, "[count.c] enter main 3\n");
  start = atof(argv[1]);
  end = atof(argv[2]);

  // We constrain the bounds to be numbers, ordered, and within the
  // range [START_FLOAT, END_FLOAT].  As a result, FLOATS_BETWEEN
  // gives a bound on the number of single-precision floating-point
  // numbers that lie in between these bounds.

  if(isnan(start) || isnan(end)) {
    fprintf(stderr, "[count.c] enter main 4\n");
    return 0;
    // fprintf(stderr, "[count.c] exit main 4\n");
  }
  // fprintf(stderr, "[count.c] exit main 3\n");

  fprintf(stderr, "[count.c] enter main 5\n");
  if(start > end) {
    fprintf(stderr, "[count.c] enter main 6\n");
    return 0;
    // fprintf(stderr, "[count.c] exit main 6\n");
  }
  // fprintf(stderr, "[count.c] exit main 5\n");
 
  fprintf(stderr, "[count.c] enter main 7\n");
  if(start < START_FLOAT) {
    fprintf(stderr, "[count.c] enter main 8\n");
    return 0;
    // fprintf(stderr, "[count.c] exit main 8\n");
  }
  // fprintf(stderr, "[count.c] exit main 7\n");

  fprintf(stderr, "[count.c] enter main 9\n");
  if(end > END_FLOAT) {
    fprintf(stderr, "[count.c] enter main 10\n");
    return 0;
    // fprintf(stderr, "[count.c] exit main 10\n");
  }
  // fprintf(stderr, "[count.c] exit main 9\n");

  fprintf(stderr, "[count.c] enter main 11\n");
  int count = 0;
  
  // We require that unsigned and float have the same size for the
  // program to operate correctly
  assert(sizeof(unsigned) == sizeof(float));

  // Iterate through the floating-point numbers in the range by
  // bit-conversion to unsigned.
  for(float current = start; current != end; count++) {
    fprintf(stderr, "[count.c] enter main 12\n");
    unsigned temp;
    memcpy(&temp, &current, sizeof(float));
    temp++;
    memcpy(&current, &temp, sizeof(float));
    // fprintf(stderr, "[count.c] exit main 12\n");
  }
  // fprintf(stderr, "[count.c] exit main 11\n");

  fprintf(stderr, "[count.c] enter main 13\n");
  // Check that the count is non-negative and bounded above by
  // FLOATS_BETWEEN
  printf("Count is %d\n", count);
  assert(count >= 0);
  assert(FLOATS_BETWEEN_MAX);
  if (count <= FLOATS_BETWEEN_BUG) {
    fprintf(stderr, "[count.c] enter main 14\n");
    printf("BUG triggered!");
    return 1;
    // fprintf(stderr, "[count.c] exit main 14\n");
  }
  
  return 0;
  // fprintf(stderr, "[count.c] exit main 13\n");
}
// Total cost: 0.036084
// Total split cost: 0.000000, input tokens: 0, output tokens: 0, cache read tokens: 0, cache write tokens: 0, split chunks: [(0, 71)]
// Total instrumented cost: 0.036084, input tokens: 3028, output tokens: 1044, cache read tokens: 0, cache write tokens: 3024
