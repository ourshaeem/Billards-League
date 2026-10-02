/**
 * Choosing a profile picture from the phone's photos: the phone's own
 * picker, with its crop tool set to a square, then shrunk to 512 pixels
 * and saved as a JPEG - before it leaves the phone.
 *
 * A phone photo is several megabytes; what's sent is a few dozen
 * kilobytes, which uploads in a moment on mobile data. The server crops,
 * shrinks and re-saves it again anyway (that's what removes the location
 * data photos carry), so this is about speed, not trust.
 *
 * No permission is asked for: the system photo picker (iOS 14+, Android
 * 13+) hands over only the photo chosen, so the app never sees the rest.
 */
import * as ImagePicker from 'expo-image-picker';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';

// The longest side of what's uploaded; the server stores 512 too.
const SIZE = 512;
const QUALITY = 0.85;

export class PhotoProblem extends Error {}

/**
 * Let the player pick and crop a photo. Resolves to a data: URL holding
 * the square JPEG to upload, or null if they backed out. Throws
 * PhotoProblem with a sentence to show them.
 */
export async function pickSquarePhoto() {
  let result;
  try {
    result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      aspect: [1, 1],
      quality: 1,
    });
  } catch {
    throw new PhotoProblem(
      "Your photos couldn't be opened. If the app asked to see them, allow it in your phone's settings and try again.",
    );
  }
  if (result.canceled || !result.assets?.length) return null;

  const asset = result.assets[0];
  try {
    // The crop tool already made it square on most phones; where it
    // didn't (or the player skipped it), take the middle square.
    const side = Math.min(asset.width, asset.height);
    const context = ImageManipulator.manipulate(asset.uri);
    if (asset.width !== asset.height && side > 0) {
      context.crop({
        originX: Math.floor((asset.width - side) / 2),
        originY: Math.floor((asset.height - side) / 2),
        width: side,
        height: side,
      });
    }
    if (side > SIZE) context.resize({ width: SIZE, height: SIZE });
    const image = await context.renderAsync();
    const saved = await image.saveAsync({ format: SaveFormat.JPEG, compress: QUALITY, base64: true });
    if (!saved.base64) throw new Error('no image data');
    return `data:image/jpeg;base64,${saved.base64}`;
  } catch {
    throw new PhotoProblem("That photo couldn't be prepared. Try a different one.");
  }
}
