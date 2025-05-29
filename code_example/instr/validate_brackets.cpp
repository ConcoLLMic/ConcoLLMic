/*
Developed by ESN, an Electronic Arts Inc. studio.
Copyright (c) 2014, Electronic Arts Inc.
All rights reserved.

...

 * Copyright (c) 1988-1993 The Regents of the University of California.
 * Copyright (c) 1994 Sun Microsystems, Inc.
*/

/*
other comments
*/

#include <stdio.h>
#include <stdlib.h>

int validate_brackets(const char *filename) {
    fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 1\n");
    FILE *file = fopen(filename, "r");
    if (!file) {
        fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 2\n");
        perror("Failed to open file");
        exit(1);
        // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 2\n");
    }
    // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 1\n");

    fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 3\n");
    char buffer[256];
    if (!fgets(buffer, 256, file)) {
        fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 4\n");
        fclose(file);
        exit(1);
        // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 4\n");
    }
    fclose(file);
    // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 3\n");

    fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 5\n");
    int balance = 0;
    // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 5\n");
    
    for (int i = 0; buffer[i] != '\0'; i++) {
        fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 6\n");
        if (buffer[i] == '{') {
            fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 7\n");
            balance++;
            // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 7\n");
        } else if (buffer[i] == '}') {
            fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 8\n");
            balance--;
            // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 8\n");
        }
        
        if (balance < 0) {
            fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 9\n");
            return -1;
            // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 9\n");
        }
        // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 6\n");
    }

    fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 10\n");
    if (balance != 0) {
        fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 11\n");
        return -1;
        // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 11\n");
    } else {
        fprintf(stderr, "[validate_brackets.cpp] enter validate_brackets 12\n");
        return 0;
        // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 12\n");
    }
    // fprintf(stderr, "[validate_brackets.cpp] exit validate_brackets 10\n");
}

int main(int argc, char *argv[]) {
    fprintf(stderr, "[validate_brackets.cpp] enter main 1\n");
    if (argc != 2) {
        fprintf(stderr, "[validate_brackets.cpp] enter main 2\n");
        fprintf(stderr, "Usage: %s <filename>\n", argv[0]);
        return 1;
        // fprintf(stderr, "[validate_brackets.cpp] exit main 2\n");
    }
    // fprintf(stderr, "[validate_brackets.cpp] exit main 1\n");
    
    fprintf(stderr, "[validate_brackets.cpp] enter main 3\n");
    int result = validate_brackets(argv[1]);
    return 0;
    // fprintf(stderr, "[validate_brackets.cpp] exit main 3\n");
}
// Total cost: 0.015955
// Total split cost: 0.000000, input tokens: 0, output tokens: 0, cache read tokens: 0, cache write tokens: 0, split chunks: [(0, 60)]
// Total instrumented cost: 0.015955, input tokens: 2398, output tokens: 904, cache read tokens: 2394, cache write tokens: 444
