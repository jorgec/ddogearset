import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function fetchExpansions() {
  console.log("Fetching Expansion Packs from DDO Wiki...");
  try {
    const headers = {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    };
    const res = await fetch("https://ddowiki.com/api.php?action=parse&page=Category:Expansion_Packs&format=json", { headers });
    const data = await res.json();
    
    // The wiki API returns the parsed HTML in data.parse.text["*"]
    // We can extract links that look like expansion packs.
    // However, Category pages in MediaWiki usually list pages in the category via a different API.
    
    // Let's use the query API for category members.
    const catRes = await fetch("https://ddowiki.com/api.php?action=query&list=categorymembers&cmtitle=Category:Expansion_Packs&cmlimit=50&format=json", { headers });
    const catData = await catRes.json();
    
    const expansions = catData.query.categorymembers
      .filter(member => member.ns === 0) // Only main namespace articles
      .map(member => member.title)
      .filter(title => !title.includes("Category") && !title.includes("DDO Store") && title !== "Expansion Packs");
      
    // Sort chronologically if possible, or just alphabetically for now since we don't have release dates easily via this API.
    // Actually, let's just dump them as they are and let the UI handle it.
    
    const outPath = path.join(__dirname, '..', 'src', 'lib', 'data', 'expansions.json');
    
    // Ensure directory exists
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    
    fs.writeFileSync(outPath, JSON.stringify(expansions, null, 2));
    console.log(`Successfully wrote ${expansions.length} expansions to ${outPath}`);
    console.log(expansions);
    
  } catch (err) {
    console.error("Failed to fetch expansions:", err);
    process.exit(1);
  }
}

fetchExpansions();
