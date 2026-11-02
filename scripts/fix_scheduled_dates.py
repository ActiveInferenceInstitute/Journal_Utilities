"""
Script to fix scheduled_date fields in the database that are stored as strings
instead of proper datetime objects.
"""

import asyncio
import datetime
import os

from dotenv import load_dotenv
from surrealdb import AsyncSurreal

load_dotenv()  # searches upward from this file, unlike a CWD-relative '.env'


async def fix_scheduled_dates() -> None:
    """Update all scheduled_date fields from string format to datetime format."""
    db_url = os.getenv("DB_URL")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    db_namespace = os.getenv("DB_NAMESPACE")

    async with AsyncSurreal(db_url) as db:
        await db.signin({"username": db_user, "password": db_password})
        await db.use(db_namespace, db_name)

        # Get all sessions with scheduled_date
        result = await db.query(
            "SELECT id, scheduled_date FROM session WHERE from_coda_json = TRUE AND scheduled_date IS NOT NONE"
        )

        if not result or len(result) == 0:
            print("No sessions with scheduled_date found")
            return

        updated_count = 0

        for session in result:
            session_id = session["id"]
            scheduled_date_str = session.get("scheduled_date", "")

            # Check if it's in the wrong format (starts with d')
            if isinstance(scheduled_date_str, str) and scheduled_date_str.startswith("d'"):
                # Extract the datetime string from d'2025-07-30T00:00:00-07:00'
                date_str = scheduled_date_str[2:-1]  # Remove d' prefix and ' suffix

                try:
                    # Parse and update
                    dt = datetime.datetime.fromisoformat(date_str)

                    # Update the record with proper datetime (parameterized)
                    await db.query(
                        "UPDATE $id SET scheduled_date = $date", {"id": session_id, "date": dt}
                    )
                    print(f"Updated {session_id}: {scheduled_date_str} -> {dt.isoformat()}")
                    updated_count += 1
                except (ValueError, TypeError) as e:
                    print(f"Failed to parse date for {session_id}: {scheduled_date_str} - {e}")
            else:
                print(f"Skipping {session_id} - already in correct format")

        print(f"\nTotal sessions updated: {updated_count}")


if __name__ == "__main__":
    asyncio.run(fix_scheduled_dates())
