// Minifies the hand-written stylesheets under sbomify/static/css in place.
//
// Vite minifies what it bundles, but the legacy sheets every public page
// loads are served by collectstatic exactly as written. The production image
// runs this on its own copy of the tree before collectstatic; running it in a
// checkout rewrites tracked source files.
//
// No browser targets are passed, so nothing is lowered or prefixed: the output
// is the same rules with whitespace and comments removed.
import { readdirSync, readFileSync, statSync, writeFileSync } from 'fs'
import { join } from 'path'
import { transform } from 'lightningcss'

const root = process.argv[2] ?? 'sbomify/static/css'

function stylesheets(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return stylesheets(path)
    return name.endsWith('.css') && !name.endsWith('.min.css') ? [path] : []
  })
}

for (const path of stylesheets(root)) {
  const source = readFileSync(path)
  const { code } = transform({ filename: path, code: source, minify: true })
  writeFileSync(path, code)
  console.log(`${path}: ${source.length} -> ${code.length} bytes`)
}
