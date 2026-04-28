## SKill to extract the information about the "variables de indec" from 5 to page 35
## The skill, should create a pipeline in dugster (using dagster-mcp) to:
-  read the document
- split the files
- analyze the document with a LLM and extract the fields
- create a json with the information
- load in a table call "bronze.indev_variables_eph"

#create the skil
