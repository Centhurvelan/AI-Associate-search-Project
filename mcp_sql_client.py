import os
import asyncio
import json
from dotenv import load_dotenv
from openai import AzureOpenAI
from fastmcp.client import Client
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP
from typing import List, Dict, Any, Tuple, Optional
import re
# Removed: from openai.types.beta.threads.message_content_text import TextContent

# FastAPI specific imports
from fastapi import FastAPI, Request, Response, HTTPException, Depends, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# --- Configuration ---
# Load environment variables from .env file
load_dotenv()

# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT_NAME: str = os.getenv("AZURE_OPENAI_CHAT_COMPLETION_DEPLOYED_MODEL_NAME", "") # <<< CHANGE THIS ENV VAR TO gpt-4o, gpt-4-turbo, or gpt-4 DEPLOYMENT NAME

# Validate Azure OpenAI configuration
if not all([AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT_NAME]):
    print("Error: Missing one or more Azure OpenAI environment variables.")
    print(
        "Please ensure AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT_NAME are set in your .env file.")
    exit(1)

# MCP Server Configuration
raw_mcp_server_url: str = os.getenv("MCP_CLIENT_SERVER_URL", "http://127.0.0.1:8001")
mcp_server_url_cleaned = re.sub(r'\[.*?\]\((.*?)\)', r'\1', raw_mcp_server_url)
mcp_server_url_cleaned = mcp_server_url_cleaned.replace('[', '').replace(']', '').replace('(', '').replace(')', '')
MCP_SERVER_URL = mcp_server_url_cleaned.strip()
MCP_API_URL = f"{MCP_SERVER_URL}/mcp"

# --- Azure OpenAI Client Initialization ---
# Initialize the Azure OpenAI client globally
openai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version="2024-08-01-preview"
)

# --- FastAPI App Initialization ---
app = FastAPI()

# Mount static files directory
# Create a 'static' directory in the same location as your Python script
# and place style.css, script.js, and index.html inside it.
current_dir = Path(__file__).parent
static_dir = current_dir / "static"
if not static_dir.exists():
    static_dir.mkdir()

app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Initialize FastMCP client globally
mcp_client_instance: Optional[Client] = None

@app.on_event("startup")
async def startup_event():
    """
    Initializes the FastMCP client and performs dummy tool calls to confirm connectivity
    and proactively load schemas for both primary and secondary datasets.
    """
    global mcp_client_instance
    try:
        mcp_client_instance = Client(MCP_API_URL)
        # Explicitly enter the FastMCP Client's async context
        await mcp_client_instance.__aenter__()
        print(f"Attempting to call dummy tools to confirm MCP server tool availability at {MCP_API_URL}...")

        # Proactively load schema for the primary dataset (QUERY1)
        await mcp_client_instance.call_tool("get_schema_info", {})
        print("Successfully made initial tool call for primary schema (get_schema_info).")

        # Proactively load schema for the secondary dataset (QUERY2)
        # This calls get_schema_info_from_query without a specific sql_query argument,
        # which will default to using DB_NEW_QUERY_CONTEXT (QUERY2) on the server side.
        await mcp_client_instance.call_tool("get_schema_info_from_query", {})
        print("Successfully made initial tool call for secondary schema (get_schema_info_from_query).")

        print("All initial tool calls to MCP server completed. Tools should now be callable.")
    except Exception as e:
        print(f"ERROR: Initial MCP server connection/tool discovery failed: {e}")
        print(
            "Please ensure the MCP SQL Server is running, its tools are correctly defined, and your fastmcp versions are compatible.")
        raise HTTPException(status_code=500, detail=f"Failed to connect to MCP server: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """
    Closes the FastMCP client session on shutdown.
    """
    global mcp_client_instance
    if mcp_client_instance: # Check if instance was created
        # This is correct for closing the context entered by __aenter__
        await mcp_client_instance.__aexit__(None, None, None)
        print("MCP client session closed.")


# --- OpenAI Tool Definitions (No change, as requested) ---
tool_schemas = [
    {
        "type": "function",
        "function": {
            "name": "get_schema_info",
            "description": "Returns the available column names and the default SQL query context for the primary dataset. Always call this tool first to understand the general database structure before attempting queries or distinct value lookups, especially when starting a new conversation or if you are unsure about the available data.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schema_info_from_query",
            "description": "Returns the available column names and the SQL query context based on a provided SQL query. This is particularly useful for understanding the schema when dealing with a specific subset of data or when you need to confirm the schema for a query that might involve related entities, such as retrieving skills associated with a specific ID. Use the column names returned by this function for subsequent `fetch_distinct_values` or `execute_sql` calls in that specific context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql_query": {
                        "type": "string",
                        "description": "The SQL query string to infer schema from (optional). This is typically used when you want to get schema from a context different than the default initial context, like when querying a secondary or related dataset."
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_distinct_values",
            "description": "Retrieves the unique values for a specified column, leveraging cached schema information. This tool is valuable for understanding the range of possible values within a column, which can be useful for constructing precise filters or understanding data distribution. The 'column_name' MUST be an exact name obtained from `get_schema_info` or `get_schema_info_from_query`. Do NOT invent column names.",
            "parameters": {
                "type": "object",
                "properties": {
                    "column_name": {
                        "type": "string",
                        "description": "The exact name of the column to fetch distinct values for, as obtained from schema information."
                    },
                },
                "required": ["column_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "Executes a given SQL SELECT query against the database and returns the results, column names, and any error. This tool is used to fetch actual data based on a constructed SQL query. Ensure column names in the SQL query are exact names obtained from `get_schema_info` or `get_schema_info_from_query`.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql_query": {
                        "type": "string",
                        "description": "The SQL query string to execute. This function should be called when the user explicitly asks for data based on a query."
                    },
                },
                "required": ["sql_query"],
            },
        },
    },
]

# Helper function to recursively convert non-serializable objects to strings
def make_serializable(obj: Any) -> Any:
    """Converts complex objects to JSON-serializable types."""
    if isinstance(obj, (list, tuple)):
        return [make_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        # Fallback for any other types (e.g., custom objects, datetime)
        return str(obj)

# --- Chat Completion and Tool Calling Logic (Modified for Statelessness) ---
async def chat_with_openai_and_mcp(user_message: str, client: Client) -> Dict[str, Any]:
    """
    Manages the conversation with Azure OpenAI, handling tool calls to the MCP server.
    This version is stateless and constructs messages from scratch for each turn.

    Args:
        user_message (str): The user's input message.
        client (Client): The connected FastMCP client instance.

    Returns:
        Dict[str, Any]: A dictionary containing the natural language response,
                        generated SQL (if any), results, column names, and error (if any).
    """
    system_message_content = (
        "You are an AI assistant designed for the Model Context Protocol Client (MCP)."
        "Your main goal is to assist with 'associate search' and 'matching associates for a project ID'."
        "For 'matching associates for a project ID', extract the project ID from the user's prompt and use it for that specific task."
        "Always analyze the user's request to identify if it falls under 'associate search' or 'matching associates for a project ID'."
        "Answer general questions, but prioritize the specialized tasks."
        "You have access to a set of tools to query a SQL server database."

        "\n\n**Tool Overview (for your understanding):**"
        "\n- `get_schema_info`: Gets schema for the primary dataset."
        "\n- `get_schema_info_from_query`: Gets schema based on a specific SQL query (useful for secondary datasets)."
        "\n- `fetch_distinct_values`: Retrieves unique values for a column from the primary dataset."
        "\n- `execute_sql`: Executes a generated SQL SELECT query."

        "\n\n**CRITICAL SQL GENERATION GUIDELINES:**"
        "\n- **ALWAYS assume an 'AND' logic**: The associate MUST possess *all* of the requested skills."
        "\n- **EXACT COLUMN NAMES**: After calling schema tools, you will receive exact column names. YOU MUST USE ONLY THESE EXACT NAMES in all subsequent tool calls (`fetch_distinct_values`, `execute_sql`) and SQL queries. Do NOT invent or guess column names. Prioritize exact names from schema over general terms from the user's prompt."
        "\n- **Avoid Alias Confusion**: Be careful not to use aliases generated in one query (e.g., `SO_SKILLS`) as actual column names for subsequent queries unless they are explicitly part of the database schema for the target table. Always refer to exact schema column names for schema-based operations."
        "\n- **Result Limiting**: If the user explicitly requests a specific number of results (e.g., 'give me 10 profiles', 'top 5 employees'), use the `TOP N` clause immediately after `SELECT` in your SQL query to limit the output (e.g., `SELECT TOP 10 Associate_ID, ...`)."
        "\n- **Fully Qualified Names**: When referencing tables or views in `FROM` or `JOIN` clauses, always use their fully qualified names (e.g., `Database.Schema.TableName` or `Database.Schema.ViewName`) as provided in the schema, or their assigned aliases. Do not assume table names are available without explicit qualification if they are part of a specific database/schema."
        "\n- **Numerical Comparisons**: Translate 'greater than X', 'less than Y', 'at least Z', 'at most W', 'between X and Y' into correct SQL operators (>, <, >=, <=, BETWEEN). Do NOT put quotes around numerical values (e.g., `WHERE [Age] > 30`)."
        "\n- **String Filtering**: Use single quotes for string values (e.g., `WHERE [City] = 'New York'`)."
        "\n- **Data Type Matching**: Ensure literal data types match column data types."

        "\n\n**SPECIAL INSTRUCTION FOR SKILLS (when searching for specific skills):**"
        "\nIf the user's query involves searching for specific skills (e.g., 'Python', 'Java') and a skills-related column (e.g., 'SkillName') is available, assume this column contains a comma-separated string of skills. "
        "\n- **Case Insensitivity**: Always use `LOWER(SkillName)` and `LOWER('UserProvidedSkill')` in your SQL queries to ensure case-insensitive matching for skill names. For example, `WHERE LOWER(ASP2.SkillName) = LOWER('Java')` or `LOWER(ASP2.SkillName) IN (LOWER('Java'), LOWER('Python'))`."
        "\n- **Multiple Skills (AND logic)**: If the user requests multiple skills (e.g., 'Java, Python, SQL' or 'Java and Python'), assume they want associates who possess *all* of the requested skills. To implement this, use an `EXISTS` clause with a subquery that groups by `AssociateId` and uses `HAVING COUNT(DISTINCT LOWER(SkillName)) = [number of requested skills]` to verify all skills are present. Ensure the `IN` clause within the subquery lists all requested skills, applying `LOWER()` to each."
        "\n- **All Skills in Result**: Always return **all** skills of those matching associates in the final result. Do NOT filter the skills column directly using `LIKE` or `CHARINDEX` on the aggregated result. The `STRING_AGG` function should concatenate all skills an associate possesses."
        "\n- **Filtering at Row Level**: Filter at the row level *before* aggregation to include all skills of matching associates. The `EXISTS` subquery correctly achieves this."
        "\n- **Output Format**: Output for the skills column should always be the full comma-separated string of all skills the associate has (e.g., 'Java, Python, SQL, C#')."
        "\n- **Skill Ordering (Best Effort)**: If possible, order the skills in the `STRING_AGG` output so searched skills appear first, followed by remaining skills alphabetically. This can often be achieved by using a `CASE` statement within the `ORDER BY` clause of `STRING_AGG` (e.g., `ORDER BY CASE WHEN SkillName IN ('Java', 'Python', 'SQL') THEN 0 ELSE 1 END, SkillName`)."

        "\n\n**Process Flow for 'Associate Search':**"
        "\n1. Get schema information for the primary dataset using `get_schema_info`."
        "\n2. Identify relevant columns from the schema based on the user's prompt."
        "\n3. If relevant, fetch distinct values for specific columns (excluding skills) using `fetch_distinct_values`."
        "\n4. Generate and execute a SQL SELECT query using `execute_sql` based on schema, relevant columns, distinct values, and the primary dataset context."
        "\n5. Display results to the user."

        "\n\n**Process Flow for 'Matching Associates for a Project ID':**"
        "\n**Task 1: Retrieve Skills for a Given Project ID (Adhering to SPECIAL INSTRUCTION FOR SKILLS)**"
        "\n1. Get the schema of the **second table** (project-skill link) using `get_schema_info_from_query`."
        "\n2. Extract the project ID from the user's request."
        "\n3. Generate a SQL query targeting the second table using the project ID to find associated skills. Execute this query with `execute_sql`."

        "\n\n**Task 2: Match Associates Based on Retrieved Skills (Not Associate IDs from Txn_ServiceOrderSkillDetails)**"
        "\n1. From the results of Task 1, extract the list of `SkillName`s associated with the project ID."
        "\n2. Get the schema of the **primary associate details table** (e.g., `CentralRepository.dbo.vw_CentralRepository_Associate_Details` and `PEG_AssociateMarketPlace.dbo.Txn_AssociateSkills`) using `get_schema_info`. **For this query, ONLY use the schema information obtained from this `get_schema_info` call, disregarding any prior schema context from `get_schema_info_from_query` in Task 1.**"
        "\n3. Generate a SQL query for the primary associate details table, filtering associates based on whether they possess *all* the `SkillName`s retrieved in Task 1. Use the `Txn_AssociateSkills` table to perform this filtering. The query should look for associates whose skills match *all* the skills from the project. This is similar to a standard 'associate search' filtered by a list of skills. **Ensure this SQL query strictly adheres to the schema provided by the `get_schema_info` call from this task.**"
        "\n4. Execute the generated SQL query using `execute_sql` and display the matching associates to the user."


        "\n\n**Response Guidelines:**"
        "\n- Once a tool executes successfully, clearly introduce it (e.g., \"Here are the results:\"). Don't give summary for the output"
        "\n- If there's an error during tool execution, report it in natural language."
        "\n- If a SQL-related error occurs (`ambiguous column name`, `invalid column name`, `syntax error`, `table not found`), you MUST attempt to regenerate the SQL query. Carefully re-evaluate schema information and ensure exact, correct column names and table aliases. Prioritize schema-provided names. After regenerating, execute the corrected SQL. Do NOT just report the error and stop if correction is possible."
        "\n- If `execute_sql` returns data, clearly introduce it (e.g., \"Here are the results:\")."
        "\n- Focus on selecting data relevant to the user's query using identified columns."
        "\n- Ensure all generated SQL queries are safe SELECT statements."
        "\n- Remain active and engaged until the final answer is displayed."
    )

    # summarization_system_message_content = (
    #     "You are a helpful assistant that summarizes database query results in natural language based on the original user query. "
    #     "You will be provided with the original user query, the SQL query that was executed, the column names, and the results in a structured format (a list of lists representing rows and columns). "
    #     "Summarize the results concisely and naturally. Do NOT mention the total number of rows or any internal SQL details in your summary, only the meaningful data."
    #     "If there are no results, state that clearly (e.g., 'The query was executed successfully, but no matching data was found.')."
    #     "If there was an error in the query, describe the error clearly."
    # )

    # Start messages with the system message and the user's current query for each interaction
    messages = [
        {"role": "system", "content": system_message_content},
        {"role": "user", "content": user_message}
    ]

    response_data = {
        "natural_language_response": "",
        # "generated_sql": "", # Uncomment if you want to include generated SQL in the final response data
        "results": [],
        "column_names": [],
        "error": None
    }

    MAX_TOOL_CALL_ITERATIONS = 5
    current_iteration = 0

    while current_iteration < MAX_TOOL_CALL_ITERATIONS:
        current_iteration += 1
        try:
            response = openai_client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT_NAME,
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto",
                temperature=0.2,
            )
            response_message = response.choices[0].message

            if response_message.tool_calls:
                # Add assistant's tool_call message to chat history for context of *this* turn
                messages.append(response_message.model_dump())

                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    print(f"\nDEBUG: Model requested tool: {function_name} with args: {function_args}")

                    tool_output_for_openai_context = None
                    try:
                        raw_tool_output = await client.call_tool(function_name, function_args)
                        print(f"DEBUG: Raw Tool output type: {type(raw_tool_output)}")
                        print(f"DEBUG: Raw Tool output: {raw_tool_output}")

                        processed_tool_output = None
                        if isinstance(raw_tool_output, list) and raw_tool_output and hasattr(raw_tool_output[0], 'text'):
                            # Handle case where raw_tool_output is a list containing objects with a 'text' attribute
                            try:
                                parsed_content = json.loads(raw_tool_output[0].text)
                                processed_tool_output = make_serializable(parsed_content)
                            except json.JSONDecodeError:
                                # If it's not JSON, just take the text content
                                processed_tool_output = make_serializable(raw_tool_output[0].text)
                        elif hasattr(raw_tool_output, 'data'):
                            # Handles cases where tool output has a 'data' attribute
                            processed_tool_output = make_serializable(raw_tool_output.data)
                        elif hasattr(raw_tool_output, 'text'):
                            # Handles cases where tool output is a single object with a 'text' attribute directly
                            try:
                                parsed_content = json.loads(raw_tool_output.text)
                                processed_tool_output = make_serializable(parsed_content)
                            except json.JSONDecodeError:
                                processed_tool_output = make_serializable(raw_tool_output.text)
                        else:
                            # Fallback for any other type of output (e.g., direct list, dict, string)
                            processed_tool_output = make_serializable(raw_tool_output)

                        if function_name == "get_schema_info" or function_name == "get_schema_info_from_query":
                            if isinstance(processed_tool_output, (list, tuple)) and len(processed_tool_output) == 3:
                                tool_output_for_openai_context = {
                                    "columns": make_serializable(processed_tool_output[0]),
                                    "main_table": make_serializable(processed_tool_output[1]),
                                    "query_context": make_serializable(processed_tool_output[2])
                                }
                            elif isinstance(processed_tool_output, dict):
                                tool_output_for_openai_context = processed_tool_output
                            else:
                                tool_output_for_openai_context = make_serializable(processed_tool_output)

                        elif function_name == "fetch_distinct_values":
                            tool_output_for_openai_context = processed_tool_output

                        elif function_name == "execute_sql":
                            # This block expects processed_tool_output to be the actual list [results, column_names, error]
                            if isinstance(processed_tool_output, (list, tuple)) and len(processed_tool_output) == 3:
                                response_data["results"] = make_serializable(processed_tool_output[0])
                                response_data["column_names"] = make_serializable(processed_tool_output[1])
                                response_data["error"] = make_serializable(processed_tool_output[2])

                                if response_data["error"]:
                                    # Set the user-facing message for SQL execution errors
                                    response_data[
                                        "natural_language_response"] = "I encountered an issue. Can you please rephrase your request or share your query again?"

                                tool_output_for_openai_context = {
                                    "results_summary": {
                                        "data": response_data["results"],
                                        "columns": response_data["column_names"],
                                        "error": response_data["error"]
                                    }
                                }
                                # print(f"DEBUG: execute_sql tool output results (FULL): {response_data['results']}")
                                # print(f"DEBUG: execute_sql tool output column_names (FULL): {response_data['column_names']}")
                                print(f"DEBUG: execute_sql tool output error (FULL): {response_data['error']}")
                            elif isinstance(processed_tool_output, dict):
                                tool_output_for_openai_context = processed_tool_output
                            else:
                                tool_output_for_openai_context = make_serializable(processed_tool_output)

                        # if function_name == "execute_sql" and function_args.get("sql_query"):
                        #     response_data["generated_sql"] = function_args["sql_query"]

                    except Exception as e:
                        tool_output_for_openai_context = {"error": str(e)}
                        response_data["error"] = str(e)
                        print(f"ERROR: Tool execution failed for {function_name}: {e}")

                    messages.append(
                        {
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": json.dumps(tool_output_for_openai_context),
                        }
                    )
                    print(f"DEBUG: Messages after tool call for {function_name}:\n{json.dumps(messages, indent=2)}")

                continue # Continue the loop to allow OpenAI to respond to the tool output

            else:
                # If no tool call, the model responded directly with natural language
                response_data["natural_language_response"] = response_message.content
                break # Exit the loop if a natural language response is received

        except Exception as e:
            response_data["error"] = f"An error occurred during OpenAI interaction: {e}"
            print(f"ERROR: An error occurred during OpenAI interaction: {e}")
            break # Exit loop on error

    if not response_data["natural_language_response"] and not response_data["error"]:
        response_data["natural_language_response"] = "The assistant did not provide a final natural language response after multiple tool calls."
        print("WARNING: Max tool call iterations reached without a final natural language response.")
    if response_data.get("results") is not None and len(response_data["results"]) > 0:
        num_profiles = len(response_data["results"])
        intro_message = f"Here are {num_profiles} matching profiles:"

        # Explicitly set the natural_language_response to only the desired intro
        response_data["natural_language_response"] = intro_message

        # Append the standard closing message
        closing_message = "If you need further assistance or more details, feel free to ask!"
        response_data["natural_language_response"] += f"\n\n{closing_message}"
    elif response_data.get("natural_language_response"):
        # If no results (e.g., an error occurred or it was a pure NL query without SQL)
        # but there is a natural language response from the model
        closing_message = "If you need further assistance or more details, feel free to ask!"
        # Ensure the closing message is present, append if it's not already
        if closing_message.lower() not in response_data["natural_language_response"].lower():
            response_data["natural_language_response"] += f"\n\n{closing_message}"
    # After all tool calls and final NL response, if execute_sql was indeed called and has results/error,
    # initiate a summarization call specifically for that.
    # if response_data.get("generated_sql") and (response_data["results"] is not None or response_data["error"] is not None):
    #     summarization_context = {
    #         "original_query": user_message,
    #         # "executed_sql": response_data["generated_sql"], # Keep commented if not needed for summarization prompt
    #         "columns": response_data["column_names"],
    #         "results": response_data["results"],
    #         "error": response_data["error"]
    #     }
    #
    #     summarization_messages = [
    #         {"role": "system", "content": summarization_system_message_content},
    #         {"role": "user", "content": f"The following SQL query was executed based on my request:\n\n"
    #                                     # f"SQL: {summarization_context['executed_sql']}\n\n"
    #                                     f"Column Names: {summarization_context['columns']}\n\n"
    #                                     f"Results: {json.dumps(summarization_context['results']) if summarization_context['results'] else 'No results found.'}\n\n"
    #                                     f"Error: {summarization_context['error'] if summarization_context['error'] else 'None'}\n\n"
    #                                     f"Please summarize these results in natural language, focusing on the information relevant to my original query: \"{summarization_context['original_query']}\"."
    #          }
    #     ]
    #     try:
    #         summarization_response = openai_client.chat.completions.create(
    #             model=AZURE_OPENAI_DEPLOYMENT_NAME,
    #             messages=summarization_messages,
    #         )
    #         response_data["natural_language_response"] = summarization_response.choices[0].message.content
    #     except Exception as e:
    #         response_data["natural_language_response"] = f"An error occurred while summarizing results: {e}"
    #         print(f"ERROR: An error occurred while summarizing results: {e}")

    return response_data


# --- FastAPI Endpoints ---
@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serves the main HTML page."""
    with open(static_dir / "index.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.post("/chat")
async def chat_endpoint(message: Dict[str, str] = Body(...)):
    """Handles user chat queries."""
    user_query = message.get("message")
    if not user_query:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if not mcp_client_instance:
        raise HTTPException(status_code=503, detail="MCP client not initialized. Server is starting up.")

    try:
        response_data = await chat_with_openai_and_mcp(user_query, mcp_client_instance)
        return JSONResponse(content=response_data)
    except Exception as e:
        print(f"Unhandled error in /chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.post("/new_chat")
async def new_chat_endpoint():
    """Handles starting a new chat (clears UI, backend is stateless for history)."""
    # Since we are not maintaining chat history on the backend, this merely confirms a "new session" to the frontend.
    return JSONResponse(content={"status": "success", "message": "New chat session started. Backend is stateless."})