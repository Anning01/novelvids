import { readFile, writeFile } from "node:fs/promises";

const START = "<!-- star-growth-card:start -->";
const END = "<!-- star-growth-card:end -->";
const cardUrl = process.env.STAR_CARD_URL;

if (!cardUrl || !cardUrl.startsWith("https://")) {
  throw new Error("STAR_CARD_URL must be an HTTPS deployment URL");
}

const readmePath = new URL("../../../README.md", import.meta.url);
const readme = await readFile(readmePath, "utf8");
const startIndex = readme.indexOf(START);
const endIndex = readme.indexOf(END);

if (startIndex < 0 || endIndex < startIndex) {
  throw new Error("README Star growth markers were not found");
}

const normalizedUrl = new URL(cardUrl);
normalizedUrl.pathname = "/card.svg";
normalizedUrl.search = "";
normalizedUrl.hash = "";

const replacement = `${START}
<p align="center">
  <a href="https://github.com/Anning01/novelvids/stargazers">
    <img src="${normalizedUrl}" width="920" alt="猫影短剧 GitHub Star 增长曲线">
  </a>
</p>
${END}`;

await writeFile(readmePath, `${readme.slice(0, startIndex)}${replacement}${readme.slice(endIndex + END.length)}`, "utf8");
