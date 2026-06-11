#!/usr/bin/env bun

import { parseArgs } from 'node:util';

const HELP = `
大众点评评价自动化工具

用法: bun run src/index.ts <命令> [参数]

命令:
  login               打开浏览器登录，保存会话
  scrape <店铺URL> [店名]  抓取店铺信息（推荐菜、评分、评价）
  generate <店铺URL> [店名] AI 生成评价草稿（需先 scrape）
  publish <草稿ID>    模拟真人发布评价
  batch  [URL...]     批量抓取+生成+发布（从 data/shops.txt 或参数读取店铺列表）
  status              查看评价进度和橙V状态

示例:
  bun run src/index.ts login
  bun run src/index.ts scrape https://www.dianping.com/shop/xxx
  bun run src/index.ts generate https://www.dianping.com/shop/xxx
  bun run src/index.ts publish xxx-20260606
  bun run src/index.ts batch
  bun run src/index.ts batch https://www.dianping.com/shop/xxx 店名
  bun run src/index.ts status
`;

async function main() {
  let args: { positionals: string[] };
  try {
    args = parseArgs({
      args: process.argv.slice(2),
      strict: false,
      allowPositionals: true,
    });
  } catch {
    console.log(HELP);
    process.exit(1);
  }

  const [command, ...cmdArgs] = args.positionals;

  if (!command || command === 'help' || command === '--help' || command === '-h') {
    console.log(HELP);
    return;
  }

  switch (command) {
    case 'login': {
      const { loginCommand } = await import('./cli/login.js');
      await loginCommand();
      break;
    }
    case 'scrape': {
      if (!cmdArgs[0]) {
        console.log('用法: bun run src/index.ts scrape <店铺URL> [店名]');
        process.exit(1);
      }
      const { scrapeCommand } = await import('./cli/scrape.js');
      await scrapeCommand(cmdArgs[0], cmdArgs[1]);
      break;
    }
    case 'generate': {
      if (!cmdArgs[0]) {
        console.log('用法: bun run src/index.ts generate <店铺URL> [店名]');
        process.exit(1);
      }
      const { generateCommand } = await import('./cli/generate.js');
      await generateCommand(cmdArgs[0], cmdArgs[1]);
      break;
    }
    case 'publish': {
      if (!cmdArgs[0]) {
        console.log('用法: bun run src/index.ts publish <草稿ID>');
        process.exit(1);
      }
      const { publishCommand } = await import('./cli/publish.js');
      await publishCommand(cmdArgs[0]);
      break;
    }
    case 'status': {
      const { statusCommand } = await import('./cli/status.js');
      await statusCommand();
      break;
    }
    case 'batch': {
      const { batchCommand } = await import('./cli/batch.js');
      await batchCommand(cmdArgs);
      break;
    }
    default:
      console.log(`未知命令: ${command}`);
      console.log(HELP);
      process.exit(1);
  }
}

main().catch((err) => {
  console.error('Fatal error:', err?.message || err);
  process.exit(1);
});
