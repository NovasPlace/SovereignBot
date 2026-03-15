# Sovereign Bot — Privacy Policy

**Last updated:** March 15, 2026

## What This Bot Does

Sovereign is a private, self-hosted autonomous AI agent operated by a single individual. It is **not** a public service. Access is restricted to explicitly authorized Telegram user IDs.

## Data Collection

### What we store
- **Messages you send to the bot** — stored locally in a PostgreSQL database on the operator's machine for context and memory
- **Voice messages** — transcribed locally, audio is not retained after transcription
- **Telegram user ID** — used solely for access control and message routing

### What we do NOT collect
- No analytics or tracking
- No data shared with third parties
- No advertising data
- No browsing history or device information
- No data sold, rented, or traded

## Data Processing

- **LLM processing** — Messages may be sent to language model APIs (NVIDIA NIM, local Ollama) for generating responses. No conversation data is stored by these providers beyond their standard API terms
- **Voice processing** — Speech-to-text runs locally via OpenAI Whisper. No audio is sent to external services
- **Economy features** — Job scouting queries freelance platform APIs using the operator's credentials. No user data is shared with these platforms

## Data Storage

All data is stored locally on the operator's hardware:
- PostgreSQL database (conversation memory, earnings tracking)
- No cloud storage
- No data replication to external servers

## Data Retention

- Conversation data is retained indefinitely in local memory for the bot's learning and context
- The operator can purge all data at any time by clearing the local database

## Access Control

- Access is restricted to Telegram user IDs explicitly listed in the bot's configuration
- Unauthorized users receive no response
- DNA token verification is used for internal agent-to-agent communication

## Security

- Input sanitization via security membrane
- Prompt injection detection and quarantine
- No credentials stored in source code
- All secrets managed via environment variables

## Your Rights

Since this is a private, single-operator bot:
- Contact the operator directly to request data deletion
- The operator can export or purge your conversation history on request

## Contact

For privacy questions, contact the bot operator directly via Telegram.

---

*This bot is a personal project. It is not operated as a commercial service.*
