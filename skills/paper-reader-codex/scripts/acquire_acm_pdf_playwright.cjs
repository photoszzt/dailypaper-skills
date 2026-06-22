const fs = require("node:fs/promises");
const path = require("node:path");
const process = require("node:process");

function parseArgs(argv) {
  const args = {
    doi: "",
    outputPath: "",
    profileDir: "",
    timeoutMs: 120000,
    headless: false,
    playwrightModule: "",
    browserExecutable: "",
  };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === "--doi") args.doi = argv[++i];
    else if (token === "--output-path") args.outputPath = argv[++i];
    else if (token === "--profile-dir") args.profileDir = argv[++i];
    else if (token === "--timeout-ms") args.timeoutMs = Number(argv[++i]);
    else if (token === "--playwright-module") args.playwrightModule = argv[++i];
    else if (token === "--browser-executable") args.browserExecutable = argv[++i];
    else if (token === "--headless") args.headless = true;
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.doi || !args.outputPath || !args.profileDir || !args.playwrightModule) {
    console.log(JSON.stringify({
      ok: false,
      method: "node-playwright",
      message: "Missing required arguments.",
    }));
    process.exit(1);
  }

  const { chromium } = require(args.playwrightModule);
  const landingUrl = `https://dl.acm.org/doi/${args.doi}`;

  try {
    await fs.mkdir(path.dirname(args.outputPath), { recursive: true });
    await fs.mkdir(args.profileDir, { recursive: true });

    const context = await chromium.launchPersistentContext(args.profileDir, {
      headless: args.headless,
      acceptDownloads: true,
      executablePath: args.browserExecutable || undefined,
    });

    const page = context.pages()[0] || await context.newPage();
    await page.goto(landingUrl, { waitUntil: "domcontentloaded", timeout: args.timeoutMs });

    const pdfLink = page.locator("a[href*='/doi/pdf/']").first();
    try {
      await pdfLink.waitFor({ state: "visible", timeout: args.timeoutMs });
      const downloadPromise = page.waitForEvent("download", { timeout: args.timeoutMs });
      await pdfLink.click();
      const download = await downloadPromise;
      await download.saveAs(args.outputPath);
      await context.close();
      console.log(JSON.stringify({
        ok: true,
        method: "node-playwright",
        pdf_path: args.outputPath,
        landing_url: landingUrl,
        browser_profile_dir: args.profileDir,
        headless: args.headless,
        browser_executable: args.browserExecutable || null,
      }));
      process.exit(0);
    } catch (error) {
      await context.close();
      console.log(JSON.stringify({
        ok: false,
        method: "node-playwright",
        message: `Playwright did not reach a downloadable ACM PDF within the timeout: ${error.message}`,
        landing_url: landingUrl,
        browser_profile_dir: args.profileDir,
        headless: args.headless,
        browser_executable: args.browserExecutable || null,
      }));
      process.exit(1);
    }
  } catch (error) {
    console.log(JSON.stringify({
      ok: false,
      method: "node-playwright",
      message: `Failed to launch Playwright browser: ${error.message}`,
      landing_url: landingUrl,
      browser_profile_dir: args.profileDir,
      headless: args.headless,
      browser_executable: args.browserExecutable || null,
    }));
    process.exit(1);
  }
}

main();
