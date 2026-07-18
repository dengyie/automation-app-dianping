const PREFIX = '[dianping]';

function timestamp(): string {
  return new Date().toISOString().replace('T', ' ').slice(0, 19);
}

export function info(msg: string) {
  console.log(`${PREFIX} ${timestamp()} INFO  ${msg}`);
}

export function warn(msg: string) {
  console.warn(`${PREFIX} ${timestamp()} WARN  ${msg}`);
}

export function error(msg: string) {
  console.error(`${PREFIX} ${timestamp()} ERROR ${msg}`);
}

export function success(msg: string) {
  console.log(`${PREFIX} ${timestamp()} OK    ${msg}`);
}

export function divider(title?: string) {
  const line = '═'.repeat(50);
  if (title) {
    console.log(`\n${line}\n  ${title}\n${line}`);
  } else {
    console.log(line);
  }
}
