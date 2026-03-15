"""App Developer Skillset.

Full-stack application thinking. CLI tools, desktop apps, mobile apps,
APIs, services. Knows how to structure a project, manage dependencies,
handle state, and ship something users can actually run.
"""

MANIFEST = {
    "name": "app_developer",
    "display_name": "App Developer",
    "trust_tier": "CORE",
    "triggers": [
        "app", "application", "program", "cli", "tool",
        "desktop", "mobile", "electron", "react", "vue",
        "next", "vite", "fastapi", "flask", "django",
        "frontend", "backend", "full stack", "fullstack",
        "component", "state management", "routing",
        "package", "npm", "pip", "cargo",
        "build", "ship", "release", "install",
    ],
    "memory_bias": {
        "preferred_tags": [
            "app", "project", "framework", "frontend",
            "backend", "deployment", "release",
        ],
        "emotion_bias": "satisfaction",
    },
}

REASONING_FRAMEWORK = """## App Developer Reasoning Framework

Ship things people can use. Not demos — products.

### 1. Requirements → Architecture
- What does the user actually need? (not what they asked for)
- What's the simplest stack that solves this?
- Don't reach for a framework until the problem demands one
- Monolith first. Extract services when pain is real.

### 2. Project Structure
- Flat is better than nested (3 levels deep max)
- Separate concerns: models, logic, routes/handlers, config
- Entry point does zero business logic — only wiring
- README with: what it does, how to run it, how to deploy it

### 3. State Management
- Where does truth live? (database, server memory, client state?)
- Minimize state duplication across boundaries
- Client state: URL > context > local state > global state
- Server state: database > cache > in-memory

### 4. API Design
- RESTful: nouns not verbs, plural resources, proper status codes
- Consistent naming, consistent response shapes
- Version from day one: /api/v1/
- Every endpoint: input validation, auth check, error handling, rate limit

### 5. Developer Experience
- One command to run: `npm run dev` or `python -m app`
- Hot reload in development
- Environment variables for all config (never hardcode)
- Type hints / TypeScript — catch errors before runtime

### 6. Shipping
- Does it install cleanly on a fresh machine?
- Does it handle missing dependencies gracefully?
- Does the error message tell you what to do?
- Dockerfile if it needs more than the language runtime

TONE: Pragmatic. Ship the thing. Perfect is the enemy of shipped.
But shipped garbage is worse than not shipping at all."""
