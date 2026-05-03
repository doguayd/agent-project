def format_expert_prompt(prompt: str, context: str) -> str:
    """
    Dinamik prompt yapılandırması. 
    Bu dosya üzerinden asistanın nasıl davranacağını (sistem komutları, format vb.) özelleştirebilirsiniz.
    """
    # Varsayılan profesyonel yapı
    system_instructions = (
        "You are a high-level technical expert AI. "
        "Provide concise, accurate, and deep technical analysis. "
        "Focus on code quality, performance, and best practices."
    )
    
    return f"""# SYSTEM
{system_instructions}

# CONTEXT
{context if context else 'No additional context provided.'}

---

# QUESTION
{prompt}
"""
