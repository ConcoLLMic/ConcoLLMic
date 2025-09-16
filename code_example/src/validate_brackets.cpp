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
    FILE *file = fopen(filename, "r");
    if (!file) {
        perror("Failed to open file");
        exit(1);
    }

    char buffer[256];
    if (!fgets(buffer, 256, file)) {
        fclose(file);
        exit(1);
    }
    fclose(file);

    int balance = 0;
    for (int i = 0; buffer[i] != '\0'; i++) {
        if (buffer[i] == '{') {
            balance++;
        } else if (buffer[i] == '}') {
            balance--;
        }
        
        if (balance < 0) {
            return -1;
        }
    }

    if (balance != 0) {
        return -1;
    } else {
        return 0;
    }
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <filename>\n", argv[0]);
        return 1;
    }
    int result = validate_brackets(argv[1]);
    return 0;
}
