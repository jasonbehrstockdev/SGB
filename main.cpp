//
// FindSquares.cpp
//
//
// Created by jason behrstock on 6/17/15.
//
// version 0.6 (edited 6/21/15)
// version 0.7 (edited 7/7/15): minor upgrades
// version 0.8 (edited 721/15): added -s mode for small world networks.
// version 0.9 (edited 1/6/16): No real change, just cleaned out old comments. TO DO: create a structure which contains "CFS components" ie the collection of squares (or just pairs of opposite edges in a square) and the support of the component. Then we can easily check as we go whether we are CFS or not; also this will be convenient for higher order of thickness.


//////Ways to speed up the program:
//1. It might be more efficient to store the square graph in an adjacency_matrix instead of a list, I want to try to implement that later to see if it increases speed.
//2. It might be faster when comparing non-edges in squares if I have these as a "set" instead of a "pair"; I set up a square function to do this, but haven't implemented a version yet to see if this speeds up the program. I tried, this it is not faster. DONE.
//3. (low priority) See if storing component type as a vertex property instead of in a vector of integers speeds things up.
//4. For svect type, since we only care about checking entries are unique, it is probably faster to make this a set instead of a vector, in which case the comparision algorithm just needs to be changed from indexing by integers to using the set iterator in the function checkAdjacentSquares.


#include <stdio.h>
#include <stdlib.h>

#include <set>
#include <vector>
#include <string>
#include <utility>
#include <algorithm>
#include <iterator>
#include <iostream>
#include <fstream>
#include<sstream>
#include <cstring>
#include <math.h>
#include <time.h>

using namespace std;
using std::vector;

#include "boost/graph/graph_traits.hpp"
#include "boost/graph/adjacency_list.hpp"
#include "boost/graph/connected_components.hpp"

using namespace boost;

////This structure will store our graphs.
typedef adjacency_list<listS, vecS, undirectedS> graphlist;


//for SW networks
#include "boost/graph/small_world_generator.hpp"
#include <boost/random/linear_congruential.hpp>

typedef boost::small_world_iterator<boost::minstd_rand, graphlist> SW_Generator;





////Squares are stored as a pair of vertices (which we will always have span a non-edge).
//// There are three functions defined in this structure. One dumps all the vertices into a set called elements, the other two each dump just one non-edge into a set (the edge sets might be faster for comparisions, but that hasn't been tried yet...)
struct square {
    pair<adjacency_list<>::vertex_descriptor, adjacency_list<>::vertex_descriptor> nonedge_1;
    pair<adjacency_list<>::vertex_descriptor, adjacency_list<>::vertex_descriptor> nonedge_2;
    
    set<adjacency_list<>::vertex_descriptor> elements() const
    {
        return {nonedge_1.first, nonedge_1.second, nonedge_2.first, nonedge_2.second};
    };
    
    
    /////this works, but is slow; it would be good to figure out a faster implementation:
//    bool operator==(const square &rhs) const 
//    {
//        return {this->elements() == rhs.elements()};
//    }
//    bool operator!=(const square &rhs)
//    {
//        return !(*this == rhs);
//    }
    
    
};





// This type will be used as an intermediate step in building the square graph.
typedef vector<square> svect;

//create a random graph.
graphlist ErdosRenyi(const float p, const unsigned long n,const int pExport, const int flag_debug,const int flag_verbose);

//converts a file to a collection of graphs to be tested.
graphlist convertline(string inputline, const int pExport, int flag_verbose, int flag_debug);

//This function puts into svect all the (unique) squares in a given graph.
svect FindSquares(const graphlist& pGraph, const int flag_debug);

//Checks whether a given square is already listed in our squarevector
bool checkSquareList(const square& pSquare, const svect& pSquareVector);

//prints as output the squarevector. Only used for debugging and for understanding details of particular examples.
void printSquareList(const svect& pSquareVector);

//checks if two squares are adjacent
bool checkAdjacentSquares(const square& pSquare_1, const square& pSquare_2);

//prints graph to file and/or cout, depending on flags.
void printGraph(const graphlist & pGraph, const unsigned long n, const int pExport, const int flag_debug, const int flag_verbose);

//converts a vector of squares to the square graph.
graphlist buildSquareGraph(const svect& pSquareVector, const int flag_debug,const int flag_verbose);

//finds the connected components in a graph. (This subroutine is not used in current implemenation.)
vector<adjacency_list<>::vertex_descriptor> findComponents(const graphlist & pGraph, const int flag_debug, const int flag_verbose);

//given a graph and a connected compoent of the derived squaregraph this finds the support in the original graph of squares in that component.
unsigned long checkSupport( graphlist & pDerivedSquareGraph, svect & pSquareVector, vector<adjacency_list<>::vertex_descriptor>& pComponentVector, unsigned long c,  const int flag_debug, const int flag_verbose);





//Creates a random graph or graphs from a file and checks them for the CFS property.
int main(int argc, const char * argv[]){
    
    
// this subroutine reads the command line arguments determining flags.
#include "flags.h"
    
    
    //p=density, n=#vertices, tests=#trials
    float p = 1;
    unsigned long n=1;
    unsigned int tests=1;
    
    
    
    //get input from command line
    if (flag_teaformatted==0)
    {
        
        p=atof(argv[flag_counter+2]);
        
        n=atoi(argv[flag_counter+1]), tests=atoi(argv[flag_counter+3]);
    }
    
    //for SW graphs
    float SW_beta=p;
    int SW_mean_degree = 0;

    if (SW_beta>1)
    {
        SW_beta=1;
    }

    float alpha=p;
    
    if (flag_alpha==1)
    {
        p= alpha * pow(n,-.5);
    }
    
    if (flag_alpha != 1)
    {
        alpha = p/pow (n, -.5);
    }
    
    // to be used for export file in case flag_export==1
    string out_file;

    
    //get input from file
    string inputfile;
    string inputfilename;
    string inputline;
    
    if (flag_teaformatted==1)
    {
        int numLines = 0;
        ifstream inputfilename(argv[2]);
        string unused;
        while (getline(inputfilename, unused) )
            ++numLines;
        
        tests=numLines;
        
        if (flag_full!=1)
        {printf("Running %d graphs from file.\n",tests);}
    }
    
    //random number generator
    srand (time(NULL));
    
    
    // cfs_total will report the number of tests which find a CFS graph
    unsigned int cfs_total=0;
    // prop_cfs will tell the percent of tests which are CFS
    float prop_cfs=0;
    
    
    
    // num_comp_total will give the total number of connected components over all the square graphs found
    unsigned int num_comp_total=0;
    // largest_support_total will sum the number of vertices which are the largest support of a component in the square graph.
    unsigned int largest_support_total=0;
    // support_size_total will sum the number of vertices (with multiplicity) which are in the support of a component in the square graph.
    unsigned int support_size_total=0;
//    //The total number of vertices of the square graphs checked (ie total number of squares).
//    unsigned int num_squares_total=0;


    
    //This is the main algorithm to check CFS for each graph:
    for (int curr_test=0; curr_test<tests; curr_test++)
    {
        int temp_cfs=0;
        unsigned long num_comp=0;
        unsigned long support_size=0;
        unsigned long largest_support=0;
        
//        int total_norm=0;
        
        
        //First we create our graph:
        
        graphlist Graph;
        
        if (flag_smallworld==0)
        {
        //Either an ER Random graph:
        if (flag_teaformatted==0)
        {
            Graph= ErdosRenyi(p,n, flag_export, flag_debug, flag_verbose);
            
        }
        
        // Or User input graphs from file:
        if (flag_teaformatted==1)
        {
            string line;
            ifstream inputfilename(argv[2]);
            if (inputfilename.is_open())
            {
                for (int lineno = 0; getline (inputfilename,line) && lineno < tests; lineno++)
                { if (lineno == curr_test)
                    inputline=line;
                }
                inputfilename.close();
            }

            Graph=convertline(inputline,flag_export,flag_verbose,flag_debug);
            n= num_vertices(Graph);
        }
        }
    
        //or a SW random graph:
        if (flag_smallworld==1)
        {
            SW_mean_degree =atoi(argv[flag_counter+4]);
            
//            boost::minstd_rand gen(time(NULL));
            boost::minstd_rand gen(rand());

            graphlist g(SW_Generator(gen,n,SW_mean_degree, SW_beta), SW_Generator(),n);
            Graph=g;
            
            printGraph(Graph, n, flag_export, flag_debug, flag_verbose);

        }
      
        
        //Now check the graph is not disconnected; if it is, this "if" loop is the end of the current test. In this case no information about the square graph is reported.
        vector<adjacency_list<>::vertex_descriptor> primary_graph_component(num_vertices(Graph));
        
        if (connected_components(Graph, &primary_graph_component[0])>1)
        {
            if (flag_verbose==1)
            {
                printf("This graph is disconnected\n");
            }
            
            if(flag_full==1) //report on individual tests:
            {
                //Output (Vertices, Density, alpha, Whether CFS, ...):
                
                cout << n << ", " << p << ", " << alpha << ", " << "0" << ", " << "Disconnected." << "\n";
            }
            continue;
        }
        
        else
        {
            //here we find all squares in Graph.
            svect squareVector=FindSquares(Graph, flag_debug);
            
            unsigned long num_squares=squareVector.size();
            
            if (flag_debug==1)
            {
                printSquareList(squareVector);
            }
            
            
            //Now we build the square graph from the list of squares.
            graphlist derivedSquareGraph = buildSquareGraph(squareVector, flag_debug, flag_verbose);
            
            
//            //////We could use this to find the components of the square graph and print out their info; instead we use the code after this.
//            auto componentVector= findComponents(derivedSquareGraph,flag_debug,flag_verbose);
//            
            
            //////Now we find the connected components of the square graph.
            ///(Perhaps this next part should be moved into the findComponents functions and we use that instead).
            vector<adjacency_list<>::vertex_descriptor> temp_component(num_vertices(derivedSquareGraph));
            
            num_comp = connected_components(derivedSquareGraph, &temp_component[0]);
            num_comp_total+=num_comp;
            

            // this next loop checks the support of each component of the square graph.
            for (unsigned int c=0; c<num_comp; c++)
            {
                unsigned long temp_support_size = checkSupport(derivedSquareGraph,squareVector, temp_component, c, flag_debug,flag_verbose);
                support_size  += temp_support_size;
                largest_support=max(largest_support, temp_support_size);
            }
            
            support_size_total+=support_size;
            largest_support_total+=largest_support;
            
            // A complete join factor consists of vertices adjacent to every
            // other vertex. Exclude it only from the CFS support target;
            // the square graph and its reported supports remain unchanged.
            unsigned long cfs_support_target = num_vertices(Graph);
            auto graph_vertices = vertices(Graph);
            for (auto v = graph_vertices.first; v != graph_vertices.second; ++v)
            {
                bool universal = true;
                for (auto u = graph_vertices.first; u != graph_vertices.second; ++u)
                {
                    if (*u != *v && !edge(*u, *v, Graph).second)
                    {
                        universal = false;
                        break;
                    }
                }
                if (universal)
                    --cfs_support_target;
            }

            // Require an actual square component, including for clique-only graphs.
            if (num_comp > 0 && largest_support == cfs_support_target)
            {
                temp_cfs=1;
                cfs_total++;
                
                if (flag_verbose==1 || flag_debug==1)
                {
                    printf("This graph is CFS\n");
                }
            }
            
            if (temp_cfs!=1)
            {
                if (flag_verbose==1 || flag_debug==1)
                {
                    printf("This graph is not CFS\n");
                }
            }
            
            // ratio_comp_avg will report the average percentage of vertices in the graph which support a component of the square graph
            float ratio_comp_avg=static_cast<float>(support_size)/(num_comp * n);
            // ratio_largest_comp will report the percentage of graph supporting the component of the square graphs with largest support.
            float ratio_largest_comp=static_cast<float>(largest_support)/(n);

            
            if(flag_full==1) //report on individual tests:
            {
                if (curr_test==0)
                {
                    //header info.
                    cout << "n, p, alpha, CFS, num_squares, num_comp, ratio_comp_avg, ratio_largest_comp\n";
                }
                
                
                //Output (Vertices, Density, alpha, Whether CFS, # squares in graph,  numbers of components of square graph, average ratio of support of component of square graph, largets ratio of support of component of square graph):
                
                cout << n << ", " << p << ", " << alpha << ", " <<  temp_cfs << ", " << num_squares <<  ", " << num_comp << ", " << ratio_comp_avg << ", " << ratio_largest_comp << "\n";
            }
            
        }
        
        //end of main part of algorithm
    }
    

//    num_comp_total
//    
//    // ratio_comp_avg will report the average percentage of vertices in the graph which support a component of the square graph
//    float ratio_comp_avg=static_cast<float>(num_squares)/(n);
//    // largest_comp_avg will report the average support of the component of the square graphs with largest support.
//    float largest_comp_avg=0;
//    //The average number of vertices of the square graph.
//    float num_squares_average=0;
    
    
    // ratio_comp_avg will report the average percentage of vertices in the graph which support a component of the square graph
    float ratio_comp_avg_total=static_cast<float>(support_size_total)/(num_comp_total * n);
    // ratio_largest_comp will report the percentage of graph supporting the component of the square graphs with largest support.
    float ratio_largest_support_total=static_cast<float>(largest_support_total)/(n * tests);
    // ratio_comp_avg will report the average percentage of vertices in the graph which support a component of the square graph

    
    
    //Info to report:
    
    if(flag_full!=1)
    {
        prop_cfs=100*static_cast<float>(cfs_total)/tests;
        printf("p=%f, alpha=%f, n=%lu, trials= %d, #CFS= %d, PercentCFS= %f, AvgSupport= %f, LargestSupport= %f \n", p, alpha,n,tests,cfs_total,prop_cfs, ratio_comp_avg_total, ratio_largest_support_total);
    }

    
    
    
    return 0;
}


//***********************************************************************************************************************************
//********************************************   FindSquares   **********************************************************************
//***********************************************************************************************************************************

//Finds all the squares in a given graph and outputs a vector of (pair-wise unique) squares.

svect FindSquares(const graphlist& pGraph, const int  flag_debug)

{
    svect tempSquareVector;
    
    auto const vs=vertices(pGraph);
 
    //routine to find squares and save them as part of a vector of squares
    for (auto vit = vs.first; vit!= vs.second; ++vit)
    {
        if (flag_debug==1)
        {
            cout << "working on vertex:" << *vit << endl;
        }
        
        auto neighbors_vit = adjacent_vertices(*vit,pGraph);
        for (auto nit=neighbors_vit.first; nit!=neighbors_vit.second; ++nit)
        {
            for (auto nit2=nit; ++nit2!=neighbors_vit.second;)
            {
				//THIS STEP WAS MISSING UNTIL 2024, so code was producing extra squares :(
				if (*nit==*nit2)
				{
					continue;
				}
                
                if (flag_debug==1)
                {
                    cout << "The pair of vertices "<< *nit << " and " << *nit2 << " are both adjacent to:" << *vit << endl;
					
					//cout << "Edge: " << edge(*nit, *nit2, pGraph).second << endl;
					
                }
     
                //remove case where the second vertex is adjacent to the third vertex
                if (edge(*nit, *nit2, pGraph).second==1)
                {continue;}

                auto neighbors_nit2 = adjacent_vertices(*nit2,pGraph);
                
                for (auto nit3=neighbors_nit2.first; nit3!=neighbors_nit2.second; ++nit3)
                {
					//cout << *vit << " and " << *nit << " and " << *nit2 << " and " << *nit3 << endl;
					
                    //remove case where the fourth vertex is the first vertex, or the fourth vertex is adjacent to the first vertex
                    if (*nit3==*vit || edge(*nit3, *vit, pGraph).second==1)
                    {
                        continue;
                    }
                    
                    auto neighbors_nit = adjacent_vertices(*nit,pGraph);
                    
                    for (auto nit4=neighbors_nit.first; nit4!=neighbors_nit.second; ++nit4) {
                        if (*nit3==*nit4)
                        {
                            
                            if (flag_debug==1)
                            {
                                cout<< "Square found with vertices"<< *vit << ", "
                                << *nit3 << ", " << *nit << ", "<< *nit2 <<endl;
                            }
                            
                            square newSquare;
                            
                            newSquare.nonedge_1.first=*vit;
                            newSquare.nonedge_1.second=*nit3;
                            newSquare.nonedge_2.first=*nit;
                            newSquare.nonedge_2.second=*nit2;
                            
                            
                            ////only add NEW squares
                            
                            
                            if (checkSquareList(newSquare, tempSquareVector)==false)
                            {
                                tempSquareVector.push_back(newSquare);
                            }
                            
                        }
                    }
                }
                
            }
            
            
            
        }
        
        
    }
    
    return tempSquareVector;
}

//***********************************************************************************************************************************
//********************************************   checkSquareList   **************************************************************
//***********************************************************************************************************************************

//Checks if pSquare is in pSquareVector. O if it is not, 1 if yes if it is already in the vector.

bool checkSquareList(const square& pSquare, const svect& pSquareVector)
{
    if (pSquareVector.empty()==1)
    {
        return false;
    }

    
////////this routine does the same as below, but it is slower...
//    for (int c=0; c<pSquareVector.size(); ++c)
//    {
//        if (pSquare.elements()==pSquareVector[c].elements())
//        {
//                return true;
//        }
//    }

    ////so does this, but this is a little faster
//    auto pElements=pSquare.elements();
//    
//    for (auto c=pSquareVector.begin(); c!=pSquareVector.end(); ++c)
//    {
//        if (pElements==c->elements())
//        {
//            return true;
//        }
//    }
    
    
    //this method seems more cumbersome than the above, but it is much faster. (I don't know why.)

    
    square pSquareReverse;
    
    pSquareReverse.nonedge_1.first =pSquare.nonedge_2.first;
    pSquareReverse.nonedge_1.second =pSquare.nonedge_2.second;
    pSquareReverse.nonedge_2.first =pSquare.nonedge_1.first;
    pSquareReverse.nonedge_2.second =pSquare.nonedge_1.second;
    

    for (int j=0;j<2; ++j)
    {
        square testSquare;
        
        if (j==0)
        {
            testSquare= pSquare;
        }
        if (j==1)
        {
            
            testSquare=pSquareReverse;
        }
        
        
        for (int c=0; c<pSquareVector.size(); ++c)
        {
            auto const & SV=pSquareVector[c];
            
            if (testSquare.nonedge_1==SV.nonedge_1)
            {
                if (testSquare.nonedge_2==SV.nonedge_2)
                {
                    return true;
                }
                
                if (testSquare.nonedge_2.first==SV.nonedge_2.second && testSquare.nonedge_2.second==SV.nonedge_2.first)
                {
                    return true;
                }
            }
            
            if (testSquare.nonedge_1.first==SV.nonedge_1.second && testSquare.nonedge_1.second==SV.nonedge_1.first)
            {
                if (testSquare.nonedge_2==SV.nonedge_2)
                {
                    return true;
                }
                
                if (testSquare.nonedge_2.first==SV.nonedge_2.second && testSquare.nonedge_2.second==SV.nonedge_2.first)
                {
                    return true;
                }
            }
        }
    }
    
    return false;
}

//***********************************************************************************************************************************
//********************************************   printSquareList   **************************************************************
//***********************************************************************************************************************************

//Prints the squares in pSquareVector.

void printSquareList(const svect& pSquareVector)
{
    for (int c=0; c<pSquareVector.size(); c++)
    {
        cout << "Square[" << c << "]=(" << pSquareVector[c].nonedge_1.first << ", "
        << pSquareVector[c].nonedge_1.second << ", "
        << pSquareVector[c].nonedge_2.first << ", "
        << pSquareVector[c].nonedge_2.second << ")"<< endl;
    }
    
    return;
}





//***********************************************************************************************************************************
//********************************************   checkAdjacentSquares   *************************************************************
//***********************************************************************************************************************************

//Checks if two squares are adjacent (or equal).

bool checkAdjacentSquares(const square& pSquare_1, const square& pSquare_2)
{
    
    
    square pSquare_1Reverse;
    
    pSquare_1Reverse.nonedge_1.first =pSquare_1.nonedge_1.second;
    pSquare_1Reverse.nonedge_1.second =pSquare_1.nonedge_1.first;
    pSquare_1Reverse.nonedge_2.first =pSquare_1.nonedge_2.second;
    pSquare_1Reverse.nonedge_2.second =pSquare_1.nonedge_2.first;
    
    
    
    
    
    if (pSquare_1.nonedge_1==pSquare_2.nonedge_1 || pSquare_1.nonedge_1==pSquare_2.nonedge_2
        || pSquare_1Reverse.nonedge_1==pSquare_2.nonedge_1 || pSquare_1Reverse.nonedge_1== pSquare_2.nonedge_2 ||
        pSquare_1.nonedge_2==pSquare_2.nonedge_1 || pSquare_1.nonedge_2==pSquare_2.nonedge_2
        || pSquare_1Reverse.nonedge_2==pSquare_2.nonedge_1 || pSquare_1Reverse.nonedge_2== pSquare_2.nonedge_2)
    {
        return true;
    }
    
    
    
    return false;
}






//***********************************************************************************************************************************
//********************************************   ErdosRenyi   ***********************************************************************
//***********************************************************************************************************************************

graphlist ErdosRenyi(const float p,const unsigned long n, const int pExport, const  int flag_debug,const int flag_verbose)
{
    //This function creates our random graph my creating a random symmetric matrix. It sets Adj[i][j]=Adj[j][i] to 0 or 1 according to whether a random number r in [0,1] exceeds p.
    
    graphlist tempGraph(n);
    
    float r;
    
    ////////This list the vertices in the graph:
    //    pair<adjacency_list<>::vertex_iterator,
    //    adjacency_list<>::vertex_iterator> vs = vertices(tempGraph);
    //
    //    copy(vs.first, vs.second,
    //              ostream_iterator<adjacency_list<>::vertex_descriptor>{
    //                  cout, "\n"});
    
    
    
    // builds the graph by adding edges when determined by a random number:
    for (int i=0;i<n;i++)
    {
        for (int j=i+1;j<n;j++)
        {
            r=(float)rand() / (float)RAND_MAX;
            if(r<p)
            {
                add_edge(i,j,tempGraph);
                
                //                //This adds the edge and prints the edge name.
                //                pair<adjacency_list<>::edge_descriptor, bool> testedge = add_edge(i,j,tempGraph);
                //                std::cout << testedge.first << "first"<< '\n';
                
            }
        }
    }
    
    
    
    
    
    
    
    //    ////Below are ways to print the graph using the boost technology
    //    if (flag_debug==1)
    //    {
    //
    //    //    This loop lists all edges and non-edges in the graph.
    //
    //        cout << "Edges in the graph: ";
    //
    //        for (int i=0;i<n;i++)
    //        {
    //            for (int j=i+1;j<n;j++)
    //            {
    //                {
    //////////This line was giving some trouble because it needs to know the graph type is undirected...
    ////                    std::pair<adjacency_list<>::edge_descriptor, bool> edgeijg= edge(i, j, tempGraph);
    //                    bool edgeijg= edge(i, j, tempGraph).second;
    //
    //
    //                    if (edgeijg==1)
    //                    {
    //                        cout << "(" << i << "," << j << ") ";
    //                    }
    //
    //                }
    //            }
    //        }
    //        cout << endl;
    //
    //
    //        ////This loop is another way to list the names of all the edges in the graph
    //        //
    //        //    pair<adjacency_list<>::edge_iterator,
    //        //    adjacency_list<>::edge_iterator> es = edges(tempGraph);
    //        //
    //        //    copy(es.first, es.second,
    //        //              ostream_iterator<adjacency_list<>::edge_descriptor>(
    //        //                  cout, "\n"));
    //        //
    //        //
    //        //
    //
    //    }
    
    
    printGraph(tempGraph, n, pExport, flag_debug, flag_verbose);
    
    
    return tempGraph;
}






//***********************************************************************************************************************************
//********************************************   buildSquareGraph   ***********************************************************************
//***********************************************************************************************************************************

//This function builds the square graph associated to the graph whose squares are listed in the vector pSquareVector.

graphlist buildSquareGraph(const svect& pSquareVector, const int flag_debug,const int flag_verbose)
{
    unsigned long n_s=pSquareVector.size();
    
    graphlist tempGraph(n_s);
    
    // builds the graph by adding edges when associated squares are adjacent:
    for (int i=0;i<n_s;++i)
    {
        for (int j=i+1;j<n_s;++j)
        {
			
//			if (flag_debug==1 )
//			{
//				cout << "i j" << i <<" " <<j << "checkAdjacentSquares(pSquareVector[i],pSquareVector[j])= " << checkAdjacentSquares(pSquareVector[i],pSquareVector[j]) << endl;
//				
//				cout << " pSquareVector[i] and  pSquareVector[j] " << endl;
//				
//				vector<square> v1={pSquareVector[i]};
//				vector<square> v2={pSquareVector[j]};
//				
//				printSquareList(v1);
//				printSquareList(v2);
//				
//				//WORKING HERE
//
//			}
			

			
            if(checkAdjacentSquares(pSquareVector[i],pSquareVector[j])==1)
            {
                add_edge(i,j,tempGraph);
            }
        }
    }

    printGraph(tempGraph, n_s, 0, flag_debug, flag_verbose);
    
    return tempGraph;
}


//***********************************************************************************************************************************
//********************************************   printGraph   *************************************************************
//***********************************************************************************************************************************

//print info of pGraph to cout or file.

void printGraph(const graphlist & pGraph, const unsigned long n_p, const int pExport, const int flag_debug, const int flag_verbose)
{
    if (num_vertices(pGraph)==0)
    {
        if (flag_verbose==1|| flag_debug==1 |pExport==1)
        {
        cout << "This graph is empty!" << endl;
        }
        return;
    }
    
    //Tea formatted graphs (actual; for debugging):
    if (flag_debug==1)
    {
        printf("Graph (actual): [0");
        for (int i=1;i<n_p;i++)
            printf(",%d",i);
        printf("]");
        
        if (num_edges(pGraph)>0)
        {
            printf(" [");
        for (int i=0;i<n_p;i++)
        {
            for (int j=i+1;j<n_p;j++)
                if (edge(i, j, pGraph).second==1)
                {printf("(%d,%d),",i,j);}
        }
        printf("\b]");
        }
        printf("\n");

    }
 
    //Tea formatted graphs (importable):
    if (flag_verbose==1|| flag_debug==1)
    {
        printf("Graph: [1");
        for (int i=1;i<n_p;i++)
            printf(",%d",i+1);
        printf("]");
        if (num_edges(pGraph)>0)
        {
            printf(" [");
            for (int i=0;i<n_p;i++)
            {for (int j=i+1;j<n_p;j++)
                {
                    if (edge(i, j, pGraph).second==1)
                {
                    printf("(%d,%d),",i+1,j+1);
                }
                }
            }
            printf("\b]");
        }
        
        printf("\n");
    }
    
        //Tea formatted graphs output to file:
        std::ofstream graphsanalyzed;
        if (pExport==1)
        {
            graphsanalyzed.open ("graphsanalyzed.txt",  std::ofstream::app);
            graphsanalyzed << "[1";
            for (int i=1;i<n_p;i++)
                graphsanalyzed << "," << i+1;
            graphsanalyzed << "] [";
            for (int i=0;i<n_p;i++)
                for (int j=i+1;j<n_p;j++)
                    if (edge(i, j, pGraph).second==1)
                    {graphsanalyzed << "(" << i+1 << "," << j+1 << "),";}
            graphsanalyzed << "(1,1)]\n";
            graphsanalyzed.close();
        }
    
    return;
}



//***********************************************************************************************************************************
//********************************************   findComponents   **********************************************************
//***********************************************************************************************************************************

//This function finds the connnected components of pGraph and assigns to each vertex a component number.

vector<adjacency_list<>::vertex_descriptor>  findComponents(const graphlist & pGraph, const int flag_debug, const int flag_verbose)
{
    
    vector<adjacency_list<>::vertex_descriptor> temp_component(num_vertices(pGraph));
    
    unsigned long num = connected_components( pGraph, & temp_component[0]);
    
    
    if (flag_verbose==1)
    {
        cout << "Total number of components: " << num << endl;
        
    }

    auto const vs=vertices(pGraph);

    for (auto vit = vs.first; vit!= vs.second; ++vit)
    {
        if (flag_debug==1)
        {
            cout << "Vertex " << *vit <<" is in component " << temp_component[*vit] << endl;
        }
    }
    
    //    if (flag_verbose==1)
    //    {
    //        vector<int> compcount(num);
    //
    //        for (int c=0; c<num; c++)
    //        {
    //            compcount[c]=count (temp_component_int.begin(),temp_component_int.end(),c);
    //        }
    //
    //        sort(compcount.begin(),compcount.end());
    //        reverse(compcount.begin(), compcount.end());
    //
    //        cout << "Components listed in decreasing size are:" < endl;
    //
    //        for (int c=0; c<num; ++c)
    //            //    for (int c=num-1; c>-1; --c)
    //        {
    //            cout << "Component number " << c << " has size " <<compcount[c] <<endl;
    //        }
    //    }
    
    return temp_component;
    
}


//***********************************************************************************************************************************
//********************************************   CheckSupport    ************************************************************************
//***********************************************************************************************************************************

//For a given collection of vertices associated to squares this program puts into a set all the underlying vertices.

unsigned long checkSupport( graphlist & pDerivedSquareGraph,  svect & pSquareVector,  vector<adjacency_list<>::vertex_descriptor> & pComponentVector, unsigned long c, const int flag_debug, const int flag_verbose)
{
    set<adjacency_list<>::vertex_descriptor> tempSet;
    
    int temp_counter=0;
    
    auto const vs=vertices(pDerivedSquareGraph);
    
    for (auto vit = vs.first; vit!= vs.second; ++vit)
    {
        if (pComponentVector[*vit]==c)
        {
			
			if  (flag_verbose==1) //debug info, added 11/21/24
			{
			std::cout << "pSquareVector[" << *vit << "] " << "is in component " << c <<endl;

			}
			
			
            temp_counter+=1;
            
            for (auto& x:pSquareVector[*vit].elements()) {
                tempSet.insert(x);
            }
        }
        
    }
    
    if  (flag_verbose==1)
    {
    set<adjacency_list<>::vertex_descriptor>::iterator set_it;
    
    std::cout << "component " << c << " is supported on " << temp_counter << " squares consisting of " << tempSet.size() << " vertices of the underlying graph: ";
    for (auto set_it=tempSet.begin(); set_it!=tempSet.end(); ++set_it)
        std::cout << ' ' << *set_it;
    std::cout << '\n';
		
    }

	
	
	
    
    return tempSet.size();
}


////***********************************************************************************************************************************
////********************************************   Graph Converter   ******************************************************************
////***********************************************************************************************************************************
//
////Converts list of TEA formated graphs to a graph.
//
//
//graphlist convertline(string inputline, const int pExport, int flag_verbose, int flag_debug)
//{
//    //string to be converted
//    //DT2:string input = "[1,2,3,4,5,6,7] [(1,2),(2,3),(3,4),(1,4),(1,5),(3,5),(2,6),(4,6),(5,7),(6,7)]";
//    //string inputline = "[1,2,3,4] [(1,2),(2,3),(3,4),(1,4)]";
//    
//
//    
//    if (flag_debug==1)
//    {
//        //print string
//        std::cout << "\nInput string: " << inputline << "\n";
//    }
//    
//    //total string length
//    unsigned long inputline_length = inputline.length();
//    
//    //when iterating through input, this stores the current character
//    string current_char = "";
//    
//    //index is integer marking end of vertex description, aka when "]" first appears
//    int index = 0;
//    
//    //a match is found to "]"
//    int match = 0;
//    
//    //place holder while iterating through input
//    int i = 0;
//    
//    //number of vertices of graph
//    int vertices = 1;
//    
//    //look for "]" and count vertices
//    while(match==0){
//        //move to next character in string
//        current_char = inputline[i];
//        
//        int is_bracket = current_char.compare("]");
//        int is_comma = current_char.compare(",");
//        
//        //if a comma is found before "]", this means there is a vertex
//        if(is_comma == 0){
//            vertices++;
//        }
//        if(is_bracket == 0){
//            match = 1;
//            index = i;
//        }
//        
//        i++;
//    }
//    
//    //    std::cout << "\nNumber of vertices: " << vertices;
//    
////    int n=vertices;
//    
//    graphlist tempGraph(vertices);
//
//    
//    //adjacency matrix
//    //  int adj[vertices][vertices];
//    
//
//    //find edges
//    //v1 and v2 are the vertices being described, v1_start and v2_start is their index in the input string
//    //first v1 is at index+4 which is where edge list begins
//    int v1_start = index + 4;
//    int v2_start = 0;
//    string v1;
//    string v2;
//    string previous_char;
//    
//    for(int i=(index+4); i<inputline_length; i++){
//        current_char = inputline[i];
//        previous_char = inputline[i-1];
//        
//        int is_comma = current_char.compare(",");
//        
//        int is_closed_parenthesis = current_char.compare(")");
//        
//        int previous_closed_parenthesis = previous_char.compare(")");
//        
//        //if a comma is found and no parenthesis in previous character, this signifies the start of v2 and end of v1
//        if(is_comma == 0 && previous_closed_parenthesis != 0){
//            
//            int v1_length = i - v1_start;
//            
//            v1 = inputline.substr(v1_start, v1_length);
//            
//            v2_start = i+1;
//        }
//        
//        //if a closed parenthesis is found, this signifies the end of v2 and start of a new v1
//        if(is_closed_parenthesis == 0 ){
//            
//            int v2_length = i - v2_start;
//            
//            v2 = inputline.substr(v2_start, v2_length);
//            
//            //update graph
//            int v1_as_int = atoi(v1.c_str());
//            int v2_as_int = atoi(v2.c_str());
//            
//            add_edge(v1_as_int - 1,v2_as_int - 1,tempGraph);
//            
//            //new v1_start
//            v1_start = i + 3;
//        }
//   
//    }
//    
//    if (flag_verbose==1)
//    {
//        printGraph(tempGraph, vertices, pExport, flag_debug, flag_verbose);
//    }
//    
//    return tempGraph;
//   
//}


//***********************************************************************************************************************************
//********************************************   Graph Converter2   ******************************************************************
//***********************************************************************************************************************************

//Converts list of TEA formated graphs to a graph. (More robust implementation)


graphlist convertline(string inputline, const int pExport, int flag_verbose, int flag_debug)
{
	//string to be converted
	//DT2:string input = "[1,2,3,4,5,6,7] [(1,2),(2,3),(3,4),(1,4),(1,5),(3,5),(2,6),(4,6),(5,7),(6,7)]";
	//string inputline = "[1,2,3,4] [(1,2),(2,3),(3,4),(1,4)]";
	
	if (flag_debug==1)
	{
		//print string
		std::cout << "\nInput string: " << inputline << "\n";
	}
	
	// use of this counter allows graph inputs where the vertices start with either 0 or 1.
	int initial_counter=((inputline.find_first_of("0")<inputline.find_first_of("1")) ? 0 : 1);
	
	auto sizeinfo=inputline.substr(0,inputline.find_first_of("]"));
	int num_vertices=stoi(sizeinfo.substr(sizeinfo.find_last_of(",")+1));
	
	auto edgeinfo=inputline.substr(inputline.find_first_of("]"));
	edgeinfo=edgeinfo.substr(edgeinfo.find_first_of("("));
	
	graphlist tempGraph(num_vertices+1-initial_counter);
	
	while (edgeinfo.find_first_of("(")!=std::string::npos)
	{
		string tempedge=edgeinfo.substr(edgeinfo.find_first_of("(")+1,edgeinfo.find_first_of(")")-1);
		
		auto comma=tempedge.find(",");
		
		auto vertex1_str=tempedge.substr(0,comma);
		auto vertex2_str=tempedge.substr(comma+1);
		
		add_edge(stoi(vertex1_str)-initial_counter,stoi(vertex2_str)-initial_counter,tempGraph);
		
		edgeinfo=edgeinfo.substr(edgeinfo.find_first_of(")")+2);
	}
	
	if (flag_verbose==1)
	{
		printGraph(tempGraph, num_vertices+1-initial_counter, pExport, flag_debug, flag_verbose);
	}
	
	return tempGraph;
	
}



