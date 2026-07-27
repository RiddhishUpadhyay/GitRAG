import logging
from typing import List, Dict, Any
from groq import Groq

from app.config import settings

logger = logging.getLogger(__name__)

def generate_answer(query: str, reranked_chunks: List[Dict[str, Any]], history: List[Dict[str, str]] = None) -> str:
    """
    Constructs a prompt with the retrieved code contexts, calls the Groq API,
    and returns the model's response.
    """
    if not settings.GROQ_API_KEY or settings.GROQ_API_KEY == "dummy_groq_key":
        logger.warning("GROQ_API_KEY not configured. Returning dummy mock response.")
        return "Error: GROQ_API_KEY is not set. Please add it to your .env file to enable LLM generation."
        
    client = Groq(api_key=settings.GROQ_API_KEY)
    
    # Construct context string
    context_blocks = []
    for i, chunk in enumerate(reranked_chunks):
        payload = chunk["payload"]
        file_path = payload.get("file_path", "unknown")
        start_line = payload.get("start_line", 1)
        end_line = payload.get("end_line", 1)
        chunk_type = payload.get("chunk_type", "code")
        content = payload.get("content", "")
        
        block = (
            f"Snippet #{i+1}\n"
            f"File: {file_path} (Lines {start_line}-{end_line}, Type: {chunk_type})\n"
            f"```\n"
            f"{content}\n"
            f"```"
        )
        context_blocks.append(block)
        
    context_str = "\n\n---\n\n".join(context_blocks)
    
    system_prompt = (
        "You are an expert technical codebase assistant. Your task is to answer user queries "
        "about a git repository using only the provided code snippets as context.\n\n"
        "Instructions:\n"
        "1. Be extremely precise and direct in your answer. Do not make up facts or assumptions outside the context.\n"
        "2. If the context doesn't contain enough information to answer, state that clearly.\n"
        "3. You MUST cite which files and lines of code you are referencing. Always format citations as markdown links: "
        "`[filename:Lstart_line-Lend_line](file_path#Lstart_line-Lend_line)`. E.g., if you mention the `app/main.py` lines 10 to 20, "
        "write it exactly as: `[main.py:L10-L20](app/main.py#L10-L20)`. This allows the UI to render clickable links.\n"
        "4. Include short code blocks in your answer if it helps illustrate your explanation, but do not dump large sections of code."
    )
    
    user_prompt = (
        f"Context Snippets:\n{context_str}\n\n"
        f"Query: {query}\n\n"
        f"Answer:"
    )
    
    logger.info("Sending query to Groq Llama-3.3-70B model...")
    try:
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})

        completion = client.chat.completions.create(
            # Using the active Llama 3.3 70B model on Groq
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.1, # Low temperature for factual code answers
            max_tokens=1500
        )
        answer = completion.choices[0].message.content
        logger.info("Successfully received answer from Groq.")
        return answer
    except Exception as e:
        logger.error(f"Failed to generate answer via Groq API: {e}")
        return f"Error communicating with Groq API: {e}"
