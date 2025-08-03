import os
import asyncio
import pyodbc
from dotenv import load_dotenv
from fastmcp import FastMCP
from typing import List, Dict, Any, Tuple, Optional


# --- Configuration ---
def load_configuration():
    """Loads configuration from environment variables for the server."""
    load_dotenv()
    config = {
        'DB_SERVER': os.getenv("DATABASE_SERVER"),
        'DB_DATABASE': os.getenv("DATABASE_NAME"),
        'UID': os.getenv("DATABASE_USERNAME"),
        'PWD': os.getenv("DATABASE_PASSWORD"),
        'DB_INITIAL_QUERY_CONTEXT': os.getenv("QUERY1"),  # Reverted to load from .env
        'MCP_SERVER_HOST': os.getenv("MCP_SERVER_HOST", "127.0.0.1"),
        'MCP_SERVER_PORT': int(os.getenv("MCP_SERVER_PORT", 8001)),
        'DB_NEW_QUERY_CONTEXT': os.getenv("QUERY2") # ADDED THIS LINE
    }
    # Validate essential database configs
    if not all([config['DB_SERVER'], config['DB_DATABASE'], config['DB_INITIAL_QUERY_CONTEXT']]):
        print(
            "Warning: Missing one or more essential database environment variables (DB_SERVER, DB_DATABASE, DB_INITIAL_QUERY_CONTEXT).")
    return config


# --- Database Connection and Operations ---
class DatabaseManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Corrected connection string for Trusted_Connection
        self.conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={self.config['DB_SERVER']};"
            f"DATABASE={self.config['DB_DATABASE']};"
            f"UID={self.config['UID']};"
            f"PWD={self.config['PWD']};"
            # f"Trusted_Connection=yes;"  # Using trusted connection
        )
        self._connection = None
        # Initialize initial_query_context from config, and main_table_for_distinct (will be set by get_schema_info)
        self.initial_query_context: Optional[str] = config.get("DB_INITIAL_QUERY_CONTEXT")
        self.main_table_for_distinct: Optional[str] = None
        self._schema_cache: Dict[str, Any] = {}  # Cache for schema info
        self._new_schema_cache: Dict[str, Any] = {} # Cache for new schema info
        self.new_query_context: Optional[str] = config.get("DB_NEW_QUERY_CONTEXT") # ADDED THIS LINE

    async def _get_connection(self):
        """Asynchronously gets a database connection."""
        if self._connection is None or self._connection.closed:
            print("Establishing new database connection...")
            try:
                loop = asyncio.get_event_loop()
                self._connection = await loop.run_in_executor(
                    None,
                    lambda: pyodbc.connect(self.conn_str, autocommit=True)
                )
                print("Database connection established.")
            except Exception as e:
                print(f"Error connecting to database: {e}")
                self._connection = None
                raise
        return self._connection

    async def execute_query(self, sql_query: str) -> Tuple[List[List[Any]], List[str], Optional[str]]:
        """
        Executes an SQL query and returns rows, column names, and error (if any).
        """
        results: List[List[Any]] = []
        column_names: List[str] = []
        db_error: Optional[str] = None
        conn = None

        try:
            conn = await self._get_connection()
            cursor = await asyncio.get_event_loop().run_in_executor(None, conn.cursor)

            print(f"Executing SQL: {sql_query}")
            await asyncio.get_event_loop().run_in_executor(None, cursor.execute, sql_query)

            if cursor.description:
                column_names = [column[0] for column in cursor.description]

            rows = await asyncio.get_event_loop().run_in_executor(None, cursor.fetchall)
            results = [list(row) for row in rows]

        except pyodbc.Error as ex:
            sqlstate = ex.args[0]
            db_error = f"Database Error ({sqlstate}): {ex.args[1]}"
            print(db_error)
        except Exception as e:
            db_error = f"An unexpected error occurred: {e}"
            print(db_error)
        finally:
            if conn and not conn.closed:
                pass  # The connection is autocommit, so we don't close it here.

        return results, column_names, db_error

    async def get_schema_info(self, use_cache: bool = True) -> Tuple[List[str], Optional[str], Optional[str]]:
        """
        Fetches schema information (column names, main table for distinct values, initial query context).
        Uses a SELECT TOP 0 query to reliably get column names and attempts to infer the main table.
        Optionally uses a cache to avoid repeated queries.
        """
        if use_cache and self._schema_cache:
            print("Returning schema information from cache.")
            return (
                self._schema_cache.get("all_columns", []),
                self._schema_cache.get("main_table_for_distinct"),
                self._schema_cache.get("initial_query_context")
            )

        print("Fetching schema information (bypassing cache or cache empty)...")
        all_columns = []
        self.main_table_for_distinct = None  # Reset

        # Ensure initial_query_context is available
        if not self.initial_query_context:
            print("initial_query_context is not set in configuration. Cannot fetch schema.")
            return [], None, None

        try:
            conn = await self._get_connection()
            cursor = await asyncio.get_event_loop().run_in_executor(None, conn.cursor)

            # Use SELECT TOP 0 to get column names reliably from the initial_query_context
            temp_query = f"{self.initial_query_context.strip()}"
            print(f"Executing temp query to get schema: {temp_query}")
            await asyncio.get_event_loop().run_in_executor(None, cursor.execute, temp_query)

            if cursor.description:
                all_columns = [column[0] for column in cursor.description]
                print(f"Schema fetched via TOP 0 query: {len(all_columns)} columns.")
            else:
                print("No columns found via TOP 0 query for schema.")

            # Attempt to infer the main table for distinct values from initial_query_context
            from_clause_match = self.initial_query_context.upper().find("FROM")
            if from_clause_match != -1:
                remaining_query = self.initial_query_context[from_clause_match + 4:].strip()
                table_name_parts = remaining_query.split()
                if table_name_parts:
                    inferred_table = table_name_parts[0].replace("[", "").replace("]", "")
                    if '.' in inferred_table:
                        inferred_table = inferred_table.split('.')[-1]

                    if inferred_table:
                        self.main_table_for_distinct = inferred_table
                        print(f"Inferred main_table_for_distinct: {self.main_table_for_distinct}")
                    else:
                        print("Could not infer a valid main table name.")
                else:
                    print("No table name found after FROM clause in initial_query_context.")
            else:
                print("FROM clause not found in initial_query_context. Cannot infer main table.")

            # Cache the schema information
            self._schema_cache = {
                "all_columns": all_columns,
                "main_table_for_distinct": self.main_table_for_distinct,
                "initial_query_context": self.initial_query_context
            }

        except pyodbc.Error as ex:
            sqlstate = ex.args[0]
            error_message = f"Database Error ({sqlstate}) during schema fetch: {ex.args[1]}"
            print(error_message)
            all_columns = []
            self.main_table_for_distinct = None
            self._schema_cache = {}  # Clear cache on error
        except Exception as e:
            print(f"An unexpected error occurred during schema fetch: {e}")
            all_columns = []
            self.main_table_for_distinct = None
            self._schema_cache = {}  # Clear cache on error

        return all_columns, self.main_table_for_distinct, self.initial_query_context

    async def get_schema_info_new_query(self, new_sql_query: str, use_cache: bool = True) -> Tuple[List[str], Optional[str]]:
        """
        Fetches schema information (column names and inferred main table) for a given new SQL query.
        This function is intended for scenarios where a different initial query context is needed for schema discovery.
        Optionally uses a cache specific to new queries to avoid repeated queries.
        """
        # Ensure the query is provided, or use the default from config if available
        query_to_use = self.new_query_context

        if not query_to_use:
            print("No new SQL query provided and DB_NEW_QUERY_CONTEXT is not set. Cannot fetch new schema.")
            return [], None

        cache_key = query_to_use # Use the query itself as part of the cache key

        if use_cache and cache_key in self._new_schema_cache:
            print(f"Returning schema information for new query from cache: {query_to_use}")
            cached_info = self._new_schema_cache[cache_key]
            return cached_info.get("all_columns", []), cached_info.get("main_table_for_distinct")

        print(f"Fetching schema information for new query (bypassing cache or cache empty): {query_to_use}")
        all_columns = []
        inferred_main_table = None


        try:
            conn = await self._get_connection()
            cursor = await asyncio.get_event_loop().run_in_executor(None, conn.cursor)

            # Use SELECT TOP 0 to get column names reliably from the new_sql_query
            # We assume the new_sql_query can be appended with ' WHERE 1=0' or similar
            # to make it a SELECT TOP 0 equivalent if it's a full SELECT statement.
            # For robustness, we will try to make it a TOP 0 query if it's not already.
            temp_query_for_schema = query_to_use.strip()
            if not temp_query_for_schema.upper().startswith("SELECT TOP 0"):
                # Attempt to create a TOP 0 query from it for schema inference
                if temp_query_for_schema.upper().startswith("SELECT"):
                    parts = temp_query_for_schema.upper().split("FROM", 1)
                    if len(parts) > 1:
                        temp_query_for_schema = f"SELECT TOP 0 {parts[0][len('SELECT'):].strip()} FROM {parts[1].strip()}"
                    else:
                        temp_query_for_schema = f"SELECT TOP 0 * FROM ({temp_query_for_schema}) AS subquery"
                else:
                    # If it's not a SELECT, we can't reliably get schema this way.
                    print(f"Provided new_sql_query is not a SELECT statement, cannot infer schema: {query_to_use}")
                    return [], None


            print(f"Executing temp query to get schema from new query: {temp_query_for_schema}")
            await asyncio.get_event_loop().run_in_executor(None, cursor.execute, temp_query_for_schema)

            if cursor.description:
                all_columns = [column[0] for column in cursor.description]
                print(f"Schema fetched via new TOP 0 query: {len(all_columns)} columns.")
            else:
                print("No columns found via new TOP 0 query for schema.")

            # Attempt to infer the main table for distinct values from the new_sql_query
            from_clause_match = query_to_use.upper().find("FROM")
            if from_clause_match != -1:
                remaining_query = query_to_use[from_clause_match + 4:].strip()
                table_name_parts = remaining_query.split()
                if table_name_parts:
                    inferred_table = table_name_parts[0].replace("[", "").replace("]", "")
                    if '.' in inferred_table:
                        inferred_table = inferred_table.split('.')[-1]

                    if inferred_table:
                        inferred_main_table = inferred_table
                        print(f"Inferred main_table_for_distinct from new query: {inferred_main_table}")
                    else:
                        print("Could not infer a valid main table name from new query.")
                else:
                    print("No table name found after FROM clause in new_sql_query.")
            else:
                print("FROM clause not found in new_sql_query. Cannot infer main table.")

            # Cache the new schema information
            self._new_schema_cache[cache_key] = {
                "all_columns": all_columns,
                "main_table_for_distinct": inferred_main_table
            }

        except pyodbc.Error as ex:
            sqlstate = ex.args[0]
            error_message = f"Database Error ({sqlstate}) during new schema fetch: {ex.args[1]}"
            print(error_message)
            all_columns = []
            inferred_main_table = None
            if cache_key in self._new_schema_cache:
                del self._new_schema_cache[cache_key] # Clear cache on error
        except Exception as e:
            print(f"An unexpected error occurred during new schema fetch: {e}")
            all_columns = []
            inferred_main_table = None
            if cache_key in self._new_schema_cache:
                del self._new_schema_cache[cache_key] # Clear cache on error

        return all_columns, inferred_main_table

    async def fetch_distinct_values(self, column_name: str) -> List[str]:
        """
        Fetches distinct values for a given column name from the main table.
        """
        print(f"Fetching distinct values for column: {column_name}")
        distinct_values: List[str] = []

        # Ensure main_table_for_distinct is populated before proceeding, using cached info if available
        if self.main_table_for_distinct is None:
            # Attempt to get schema info, which will populate main_table_for_distinct and cache
            print("Main table not yet defined, attempting to fetch schema info first...")
            _, self.main_table_for_distinct, _ = await self.get_schema_info(use_cache=True)
            if self.main_table_for_distinct is None:
                print("Failed to determine main table for distinct value fetching.")
                return distinct_values

        if not column_name.isalnum():  # Basic alphanumeric check for column name safety
            print(f"Invalid column name for distinct values: {column_name}")
            return distinct_values

        # Sanitize main_table_for_distinct and column_name before using in query
        safe_table_name = self.main_table_for_distinct.replace("'", "''").replace("--", "")
        safe_column_name = column_name.replace("'", "''").replace("--", "")

        sql_query = f"SELECT DISTINCT [{safe_column_name}] FROM [{safe_table_name}] WHERE [{safe_column_name}] IS NOT NULL ORDER BY [{safe_column_name}]"
        results, _, db_error = await self.execute_query(sql_query)

        if not db_error and results:
            distinct_values = [str(row[0]) for row in results if row and row[0] is not None]
            print(f"Found {len(distinct_values)} distinct values for {column_name}.")
        else:
            print(f"Could not fetch distinct values for {column_name}. Error: {db_error}")

        return distinct_values


# --- MCP Application ---
config = load_configuration()
db_manager = DatabaseManager(config)

# Initialize FastMCP application directly
mcp_app = FastMCP()


@mcp_app.tool()
async def get_schema_info() -> Tuple[List[str], Optional[str], Optional[str]]:
    """
    Returns the available column names, the main table for distinct values,
    and the initial SQL query context, utilizing schema caching.
    """
    return await db_manager.get_schema_info(use_cache=True)

@mcp_app.tool()
async def get_schema_info_from_query(sql_query: Optional[str] = None) -> Tuple[List[str], Optional[str], str]: # <--- ADDED 'str' for the query context
    """
    Returns the available column names, the main table for distinct values,
    AND the SQL query context itself, based on a provided SQL query,
    utilizing schema caching for the new query.
    If sql_query is None, it defaults to using DB_NEW_QUERY_CONTEXT from config.
    """
    # Call the existing function to get columns and main_table
    columns, main_table = await db_manager.get_schema_info_new_query(db_manager.new_query_context, use_cache=True)

    # The original request from the client for 'new query context' (QUERY2)
    # arrives when sql_query is None. In this case, db_manager.new_query_context
    # should hold the value of QUERY2 from your .env.
    query_context_to_return = db_manager.new_query_context

    # Ensure query_context_to_return is not None (it should be if new_query_context is set)
    # If for some reason it's still None (e.g., QUERY2 not configured), you might return an empty string
    # or handle it as an error, but assuming it's correctly set.
    if query_context_to_return is None:
        query_context_to_return = "" # Fallback, though ideally it should be set

    return columns, main_table, query_context_to_return # <--- IMPORTANT: Returned the query context here


@mcp_app.tool()
async def fetch_distinct_values(column_name: str) -> List[str]:
    """
    Fetches distinct values for a specified column, leveraging cached schema info.
    """
    return await db_manager.fetch_distinct_values(column_name)


@mcp_app.tool()
async def execute_sql(sql_query: str) -> Tuple[List[List[Any]], List[str], Optional[str]]:
    """
    Executes a given SQL query and returns the results, column names, and any error.
    """
    # Basic validation: Only allow SELECT queries from client for safety
    if not sql_query.strip().upper().startswith("SELECT"):
        return [], [], "Only SELECT queries are allowed."

    return await db_manager.execute_query(sql_query)


# --- Run the FastMCP Server ---
if __name__ == "__main__":
    host = config['MCP_SERVER_HOST']
    port = config['MCP_SERVER_PORT']
    print(f"Starting MCP SQL Server on http://{host}:{port}")

    # The canonical way to start FastMCP applications.
    mcp_app.run(
        host=host,
        port=port,
        transport="streamable-http"
    )