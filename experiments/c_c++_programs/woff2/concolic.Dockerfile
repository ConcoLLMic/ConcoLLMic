# Use the final stage from Symsan
FROM concolic AS bc

USER root

ENV DEBIAN_FRONTEND=noninteractive


# -------------------------------------------------------------
# Download and extract bc
# -------------------------------------------------------------
WORKDIR /
RUN git clone --recursive https://github.com/google/woff2.git && cd woff2 && git reset --hard 0f4d304faa1c62994536dc73510305c7357da8d4 && cd brotli && git reset --hard 533843e3546cd24c8344eaa899c6b0b681c8d222
RUN mv woff2 /woff2-gcov

COPY ./woff2-instr.tar.gz /woff2-instr.tar.gz
RUN tar -xzf /woff2-instr.tar.gz

# -------------------------------------------------------------
# Build bc with Instr
# -------------------------------------------------------------
WORKDIR /woff2-instr
RUN CC=gcc CXX=g++ make clean all


# -------------------------------------------------------------
# Build bc with GCOV
# -------------------------------------------------------------
WORKDIR /woff2-gcov
RUN CC=gcc CXX=g++ CFLAGS="-fprofile-arcs -ftest-coverage" CXXFLAGS="-fprofile-arcs -ftest-coverage" LFLAGS="-fprofile-arcs -ftest-coverage" LDFLAGS="-fprofile-arcs -ftest-coverage" make clean all



# -------------------------------------------------------------
# Prepare testing directory
# -------------------------------------------------------------

COPY ./seed_execs /seed_execs
COPY ./run.sh /run.sh
COPY ./coverage.sh /coverage.sh

CMD ["/bin/bash"]
