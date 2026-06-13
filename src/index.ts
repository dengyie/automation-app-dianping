#!/usr/bin/env bun

import { parseArgs } from 'node:util';

const HELP = `
大众点评评价自动化工具

用法: bun run src/index.ts <命令> [参数]

命令:
  login               打开浏览器登录，保存会话
  check               检查环境配置（浏览器/session/python/slidex）
  discover            从收藏夹/浏览历史发现店铺，追加到 data/shops.txt
  scrape <店铺URL> [店名]  抓取店铺信息（推荐菜、评分、评价）
  generate <店铺URL> [店名] AI 生成评价草稿（需先 scrape）
  prepare [--json] [--output=文件]  生成发布清单（Markdown/JSON）
  export-mobile [--output=文件]  导出手机版 HTML 清单（可直接复制）
  prepare-photos [草稿ID]  准备照片（复制到统一目录，手机友好命名）
  publish <草稿ID>    模拟真人发布评价（浏览器自动化，已废弃）
  app-publish <草稿ID> [设备ID]  通过 Appium 在 Android App 内发布评价
  explore [店铺URL] [店名]  探索移动端 H5 页面，查找写评价入口
  batch  [URL...]     批量抓取+生成+发布（从 data/shops.txt 或参数读取店铺列表）
  status              查看评价进度和橙V状态

示例:
  bun run src/index.ts login
  bun run src/index.ts scrape https://www.dianping.com/shop/xxx
  bun run src/index.ts generate https://www.dianping.com/shop/xxx
  bun run src/index.ts prepare
  bun run src/index.ts prepare --json --output=checklist.json
  bun run src/index.ts export-mobile
  bun run src/index.ts prepare-photos
  bun run src/index.ts app-publish mock-shop-001-20260613
  bun run src/index.ts app-publish mock-shop-001-20260613 emulator-5554
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
    case 'check': {
      const { checkCommand } = await import('./cli/check.js');
      await checkCommand();
      break;
    }
    case 'discover': {
      const { discoverCommand } = await import('./cli/discover.js');
      await discoverCommand();
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
    case 'app-publish': {
      if (!cmdArgs[0]) {
        console.log('用法: bun run src/index.ts app-publish <草稿ID> [设备ID]');
        console.log('示例: bun run src/index.ts app-publish mock-shop-001-20260613');
        console.log('     bun run src/index.ts app-publish mock-shop-001-20260613 emulator-5554');
        process.exit(1);
      }
      const { appPublishCommand } = await import('./cli/app-publish.js');
      await appPublishCommand(cmdArgs[0], cmdArgs[1]);
      break;
    }
    case 'prepare': {
      const { prepareCommand } = await import('./cli/prepare.js');
      const options: { json?: boolean; output?: string } = {};
      // Read from process.argv directly since parseArgs filters options
      if (process.argv.includes('--json')) options.json = true;
      const outputArg = process.argv.find(a => a.startsWith('--output='));
      if (outputArg) options.output = outputArg.split('=')[1];
      await prepareCommand(options);
      break;
    }
    case 'export-mobile': {
      const { exportMobileCommand } = await import('./cli/export-mobile.js');
      const options: { output?: string } = {};
      const outputArg = process.argv.find(a => a.startsWith('--output='));
      if (outputArg) options.output = outputArg.split('=')[1];
      await exportMobileCommand(options);
      break;
    }
    case 'prepare-photos': {
      const { preparePhotosCommand } = await import('./cli/prepare-photos.js');
      await preparePhotosCommand(cmdArgs[0]);
      break;
    }
    case 'status': {
      const { statusCommand } = await import('./cli/status.js');
      await statusCommand();
      break;
    }
    case 'explore': {
      const { exploreCommand } = await import('./cli/explore.js');
      await exploreCommand(cmdArgs[0] || undefined, cmdArgs[1] || undefined);
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
