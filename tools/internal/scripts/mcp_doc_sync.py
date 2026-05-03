import asyncio
import os
import sys
import json
from pathlib import Path

# Proje kök dizinini sys.path'e ekle (main.py'den import yapabilmek için)
PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from main import bootstrap
except ImportError as e:
    print(f"Error: bootstrap import failed. Root: {PROJECT_ROOT}")
    print(f"Error detail: {e}")
    sys.exit(1)

async def generate_markdown():
    print("Bootstrap | Initializing MCP Server for introspection...")
    mcp, logger = bootstrap()
    
    tools = await mcp.list_tools()
    print(f"Sync | Found {len(tools)} registered tools.")
    
    md_content = [
        "# MasterMCP Araç Dokümantasyonu",
        "",
        "Bu döküman, sunucuda kayıtlı tüm araçların teknik detaylarını ve LLM'e (asistan) sunulan tam açıklamalarını içerir.",
        "",
        "> [!NOTE]",
        "> Bu dosya otomatik olarak oluşturulmuştur. Güncellemek için `scripts/mcp_doc_sync.py` betiğini çalıştırın.",
        "",
        "## Araç Listesi",
        ""
    ]
    
    # Araçları isimlerine göre sırala
    sorted_tools = sorted(tools, key=lambda x: x.name)
    
    for tool in sorted_tools:
        md_content.append(f"### `{tool.name}`")
        
        # Docstring temizliği
        desc = tool.description or "Açıklama bulunmuyor."
        md_content.append(f"**Açıklama:** \n {desc}")
        
        # Parametreler (Input Schema)
        if hasattr(tool, "input_schema"):
            schema = tool.input_schema.model_json_schema()
            props = schema.get("properties", {})
            required = schema.get("required", [])
            
            if props:
                md_content.append("- **Parametreler:**")
                for param_name, details in props.items():
                    p_type = details.get("type", "any")
                    p_desc = details.get("description", "Açıklama yok.")
                    req_star = "*" if param_name in required else ""
                    md_content.append(f"  - `{param_name}{req_star}` ({p_type}): {p_desc}")
        
        md_content.append("")
        md_content.append("---")
        md_content.append("")

    target_file = os.path.join(PROJECT_ROOT, "mcp_tools_documentation.md")
    with open(target_file, "w", encoding="utf-8") as f:
        f.write("\n".join(md_content))
    
    print(f"Sync | Dokümantasyon başarıyla güncellendi: {target_file}")

if __name__ == "__main__":
    asyncio.run(generate_markdown())
