FROM experiment7pending
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /
RUN wget http://ftp.gnu.org/gnu/texinfo/texinfo-6.8.tar.xz
RUN tar -xf texinfo-6.8.tar.xz
RUN cd texinfo-6.8; \
    ./configure --prefix=/texinfo; \
    make -j$(nproc); make install

ENV PATH=/texinfo/bin:$PATH

RUN wget https://ftp.gnu.org/gnu/bc/bc-1.08.1.tar.gz
RUN tar -xzf bc-1.08.1.tar.gz

RUN cp -r bc-1.08.1 /bc-gcov && cp -r bc-1.08.1 /bc-klee

WORKDIR /bc-gcov
RUN CC=gcc CXX=g++ ./configure
RUN CC=gcc CXX=g++ make AM_CFLAGS="-fprofile-arcs -ftest-coverage"

ENV LLVM_COMPILER="clang"
WORKDIR /bc-klee
RUN CC="wllvm" CXX="wllvm++" ./configure --disable-nls CFLAGS="-g -O1 -Xclang -disable-llvm-passes -D__NO_STRING_INLINES -D_FORTIFY_SOURCE=0 -U__OPTIMIZE__"
RUN CC="wllvm" CXX="wllvm++" make
RUN extract-bc bc/bc
RUN opt -strip-debug ./bc/bc.bc -o ./bc/stripped.bc; mv bc/stripped.bc bc/bc.bc

RUN pip install gcovr

COPY ./seeds_klee /seeds
COPY ./run.sh /run.sh
COPY ./coverage.sh /coverage.sh

RUN chmod +x /run.sh
RUN chmod +x /coverage.sh

CMD ["/bin/bash"]