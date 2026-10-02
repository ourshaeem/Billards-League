/**
 * Turning a photo someone picks into a profile picture: cropped to a
 * square from its middle, shrunk, and saved as a JPEG - before it leaves
 * the browser.
 *
 * A phone photo is several megabytes; what's sent is a few dozen
 * kilobytes, which uploads in a moment on a weak connection. The server
 * crops, shrinks and re-saves it again anyway (that's what removes the
 * location data photos carry), so this is about speed, not trust.
 */

// The longest side of what's uploaded; the server stores 512 too.
const SIZE = 512;
const QUALITY = 0.88;
// Beyond this a "photo" is more likely a video or a scan; refuse it
// rather than freeze the tab decoding it.
const MAX_FILE_BYTES = 30 * 1024 * 1024;

export class PhotoProblem extends Error {}

/** A data: URL holding the square JPEG to upload. Throws PhotoProblem. */
export async function squarePhoto(file) {
  if (!file) throw new PhotoProblem('Choose a picture to upload.');
  if (file.type && !file.type.startsWith('image/')) {
    throw new PhotoProblem("That file isn't a picture. Choose a JPEG or PNG photo.");
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new PhotoProblem('That file is too big. Choose a photo under 30 MB.');
  }

  const image = await decode(file);
  const width = image.naturalWidth ?? image.width;
  const height = image.naturalHeight ?? image.height;
  const side = Math.min(width, height);
  if (!side) throw new PhotoProblem("That picture couldn't be read. Try a different one.");

  const out = Math.min(SIZE, side);
  const canvas = document.createElement('canvas');
  canvas.width = out;
  canvas.height = out;
  const context = canvas.getContext('2d');
  // See-through parts of a PNG go on white, not black.
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, out, out);
  context.imageSmoothingQuality = 'high';
  context.drawImage(image, (width - side) / 2, (height - side) / 2, side, side, 0, 0, out, out);
  image.close?.();

  return canvas.toDataURL('image/jpeg', QUALITY);
}

/**
 * The picture, decoded the right way up. Phones often save a photo
 * sideways with a note saying which way to turn it; both routes here
 * follow the note.
 */
async function decode(file) {
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch {
      // Older browsers refuse the option; fall through to <img>.
    }
  }
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      // HEIC photos from iPhones can't be read by most desktop browsers.
      reject(
        new PhotoProblem(
          "That picture couldn't be read by this browser. Try a JPEG or PNG - or a screenshot of it.",
        ),
      );
    };
    img.src = url;
  });
}
