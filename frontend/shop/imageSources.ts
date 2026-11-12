type ImageSources = {src: string; srcSet?: string};

// Only the known external CDN offers this larger image. Local hosting uses the
// file that was prepared; it never invents a local derivative path.
export function expandedImageSource(src:string):string {
  try {
    const url=new URL(src);
    if(url.origin!=='https://m.media-amazon.com'||url.search||url.hash)return src;
    const match=/^\/images\/I\/([A-Za-z0-9+_%=-]+)(?:\._[^/]+_)?\.jpe?g$/i.exec(url.pathname);
    return match?`${url.origin}/images/I/${match[1]}._SL1500_.jpg`:src;
  } catch {return src;}
}

// Amazon's CDN size suffix belongs here, not in the card markup. Local asset
// URLs and providers without this transformation contract keep their one file.
export function cardImageSources(src: string): ImageSources {
  let url: URL;
  try { url = new URL(src); } catch { return {src}; }
  if (url.origin !== 'https://m.media-amazon.com' || url.search || url.hash) return {src};
  const image = /^\/images\/I\/([A-Za-z0-9+_%=-]+)(?:\._AC_(?:UL|SL)\d+_)?\.jpe?g$/i.exec(url.pathname);
  if (!image) return {src};
  const base = `${url.origin}/images/I/${image[1]}`;
  const candidates = [1, 1.5, 2, 2.5, 3].map(density => ({
    density,
    url: `${base}._AC_UL${320 * density}${density === 1 ? '_' : '_FMwebp_QL65_'}.jpg`,
  }));
  return {src: candidates[0].url, srcSet: candidates.map(candidate => `${candidate.url} ${candidate.density}x`).join(', ')};
}
