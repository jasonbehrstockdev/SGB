Square Graph Builder:

This program will build the square graph associated to any give graph and 
report whether or not it is CFS (and also show the component structure of 
the associated square graph).

To run it with a file sample.txt which contains at least one graph (or 
several each on their own line) one uses the -t flag

./SGB -t sample.txt 

To see both the output graph and the components, also use the verbose flag: -v 


./SGB -tv sample.txt 

If you want additional info about the square graph you can run it in debug 
mode: -d

./SGB -td sample.txt 

or both debug and verbose output:

./SGB -tdv sample.txt 