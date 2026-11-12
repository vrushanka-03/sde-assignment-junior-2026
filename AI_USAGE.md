\## Tools used



\- Chatgpt for debugging and test-case suggestions.



\## What I used them for



\- Understanding assignment requirements and breaking them into implementation steps.

\- Exploring Python and SQLite implementation approaches.

\- Getting assistance with code drafts, debugging, and test-case suggestions.

\- Reviewing edge cases in data validation, event reconciliation, and reporting.



\## What I wrote or decided myself



\- Selected Assignment A and analyzed the supplied datasets and schemas.

\- Worked through the database design and processing flow.

\- Executed and debugged the implementation locally.

\- Made decisions about duplicate merging, event linking, orphan handling, and data-quality reporting.

\- Verified the generated outputs and investigated unmatched events.



\## Where the AI was wrong or unhelpful



\- An initial assumption about the disposition catalogue path was incorrect; I checked the supplied directory and corrected the path.

\- The initial event-ingestion code did not handle missing phone numbers safely. I identified the execution error and corrected the phone-hashing logic.

\- A payload-sanitization helper was missing from the initial implementation, so I added it before continuing.



\## How I verified AI-generated code



\- Executed both supplied data drops.

\- Ran the automated test suite: 25 tests passed.

\- Generated and inspected all five required reports.

\- Queried SQLite to inspect event-link statuses and investigate orphan events.

\- Checked the data-quality metrics and reviewed the implementation locally.



The automated tests cover normalization and lead validation. Event ingestion, reconciliation, and reporting were additionally checked through manual execution and SQL queries.

