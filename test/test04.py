# Test LpVariable

from pulp import *


# defining list of products
products = ['cola','peanuts', 'cheese', 'beer']
itemsets = ['x1','x2', 'x3']

#disctionary of the costs of each of the products is created
costs = {'cola' : 5, 'peanuts' : 3, 'cheese' : 1, 'beer' : 4 }

# dictionary of frequent itemsets
itemset_dict = { "x1" : (("cola", "peanuts"),10),
           "x2" : (("peanuts","cheese"),20),
           "x3" : (("peanuts","beer"),30)
           }

products_var=LpVariable.dicts("Products", products, 0)
itemsets_var=LpVariable.dicts("Itemsets", itemsets, 0)

#my_lp_program.writeLP("CheckLpProgram.lp")