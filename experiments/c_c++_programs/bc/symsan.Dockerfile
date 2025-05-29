# Use the final stage from Symsan
FROM symsan AS bc

USER root

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get install -y \
    texinfo yacc && \
    rm -rf /var/lib/apt/lists/*


# -------------------------------------------------------------
# Download and extract bc
# -------------------------------------------------------------
WORKDIR /
RUN wget https://ftp.gnu.org/gnu/bc/bc-1.08.1.tar.gz
RUN tar -xzf bc-1.08.1.tar.gz

RUN cp -r bc-1.08.1 /bc-gcov && cp -r bc-1.08.1 /bc-symsan


# -------------------------------------------------------------
# Build bc with Symsan
# -------------------------------------------------------------
WORKDIR /bc-symsan
RUN CC=/workdir/symsan/build/bin/ko-clang CXX=/workdir/symsan/build/bin/ko-clang++ ./configure
RUN CC=/workdir/symsan/build/bin/ko-clang CXX=/workdir/symsan/build/bin/ko-clang++ make


# -------------------------------------------------------------
# Build bc with GCOV
# -------------------------------------------------------------
WORKDIR /bc-gcov
RUN CC=gcc CXX=g++ ./configure
RUN CC=gcc CXX=g++ make AM_CFLAGS="-fprofile-arcs -ftest-coverage"


# -------------------------------------------------------------
# Prepare testing directory
# -------------------------------------------------------------

COPY ./seeds /seeds
COPY ./run.sh /run.sh
COPY ./coverage.sh /coverage.sh

CMD ["/bin/bash"]
