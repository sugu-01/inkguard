
import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from supabase import create_client

load_dotenv(Path(__file__).resolve().parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_SECRET_KEY must be set in backend/.env"
    )

supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

mcp = MCPServer("InkGuard")


def get_company_id(company_name: str) -> str:
    """Find the database ID for a company."""
    result = (
        supabase.table("companies")
        .select("id")
        .eq("name", company_name)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise ValueError(f"Company not found: {company_name}")

    return result.data[0]["id"]


@mcp.tool()
def get_company_rules(
    company_name: str = "InkGuard Demo Company",
) -> list[dict]:
    """Retrieve approved advertising guidelines for a company."""
    company_id = get_company_id(company_name)

    result = (
        supabase.table("rules")
        .select("id,type,page,quote,terms")
        .eq("company_id", company_id)
        .eq("approved", True)
        .execute()
    )

    return result.data


@mcp.tool()
def get_approved_facts(
    company_name: str = "InkGuard Demo Company",
) -> list[dict]:
    """Retrieve approved facts, owners, and expiry dates for a company."""
    company_id = get_company_id(company_name)

    result = (
        supabase.table("approved_facts")
        .select("id,kw,val,owner,expires")
        .eq("company_id", company_id)
        .execute()
    )

    return result.data


if __name__ == "__main__":
    mcp.run(transport="stdio")
