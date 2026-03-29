# importing google photos shared albums (with ur friend's photos) into immich

In 2026, I decided it was high time to move off Google Photos, and migrate over to a self-hosted [Immich](https://immich.app/) instance.

The "traditional" way to do this is to kick off a [Google Takeout](https://takeout.google.com/) request + import the resulting data via [`immich-go`](https://github.com/simulot/immich-go). This works great, with one big "but": Google Takeout does _not_ include any photos your friends have shared with you!

Ok, fine, whatever. So then, I went and tried to manually plug this gap by downloading each shared album from Google Photos and importing the resulting zips into Immich. Again, this "works", but with quite a few caveats:

1. The date/time data for shared photos is all mangled / incorrect for whatever reason (e.g: timezones are set to UTC??)
2. You lose all context on which of your friends uploaded which photos (sad!)
3. When those zipped manual download archives are then uploaded via `immich-go` (via the `from-folder` import mode), live photos aren't properly joined.

The end result is an album that's "imported", but not particularly pleasant to interact with.

Honestly, this _sucks_. Shame on Google for making it so damn hard to migrate off their platform.

"Oh, it's so easy to move off Google Photos! Just use Google Takeout!" Yeah, ok guys... like the average user is gonna be thrilled to have all their shared photo albums that they collaborated with their friends on end up mostly-empty. _sigh_.

On the bright side - it's 2026, and according to Twitter, "code is cheap now", so here is a collection of LLM generated slop scripts that scrape metadata from Google Photos shared albums, and apply it to the imported albums in Immich.

The end result is Immich albums that are

- Sorted in the right order as your Google albums
- Properly handle live photos
- Are tagged with "Uploaded by: {name}"

> [!WARNING]
> This is all unreviewed, unscrutinized, 100% free-range LLM generated slop. These scripts worked for me, but obviously, your mileage will vary.
>
> Scripts have `--dry-run` flags, but the logic is all LLM generated, so _please_ audit the code yourself before running it.
>
> **BACKUP YOUR IMMICH SERVER AND PHOTOS BEFORE GOING THROUGH THIS WORKFLOW**
>
> If one of these scripts ends up corrupting your Immich instance and replacing every image with a slightly differently cropped photo of Richard Stallman - don't say I didn't warn you.

## 🚀 Workflow

Very important context: I only had ~50 Google Photos shared albums I care to import.

~50 albums is _right_ on the precipice where it _might_ have made sense to automate things to run across my entire Google Photos library... but I decided it'd be easier to just manually run these steps on a per-album basis, rather than try to add any kind of finicky "multi-album" automation.

If you have a massive number of albums - Godspeed 🫡

### Step 0: Download and Import shared albums from Google Photos

First and foremost: use `immich-go`'s [`from-google-photos`](https://github.com/simulot/immich-go/blob/main/docs/commands/upload.md#from-google-photos) flow to get a "baseline" import of your Google Photos albums into Immich.

Then, to fill in the gaps with your friend's photos:

- For each of your albums, find the button that says "Download All". Click it.
  - Google doesn't _want_ you to pipeline this, but you are able to kick off simultaneous downloads if you wait to click "Download All" once the previous download has started downloading in earnest.
- Once all your albums are downloaded, run `immich-go upload from-folder --server="..." --api-key="..." --folder-as-album FOLDER /path/to/your/shared/albums/*.zip`
  - Conveniently, this will merge your Google Takeout generated albums with your manually downloaded shared photo albums (and even de-dupe assets pre-upload!)

And now, it's time to bring out the _slop_.

### Step 1: Scrape Google Photos Shared Album Metadata

Google does _not_ make it easy to dump the metadata of each photo of a shared album.

Maybe someone with more time and patience could reverse engineer the APIs they use to fetch metadata and do things more efficiently, but I went full [grug mode](https://grugbrain.dev/) and generated a javascript bookmarklet that literally just:

- Scrapes metadata from the HTML inside the "Info" box of a photo
- Hits the "view next photo" button
- Loops until you've reached the end of the album

> Protip: depending on how fast your computer + internet connection is (not to mention how wide your monitor is!), you can open a whole bunch of windows (not tabs! the window must be focused for the bookmarklet to work!!) and parallelize the scraping.
>
> It took me ~45 mins with ~6 Chrome windows to dump metadata across my ~50 albums (each containing between 50-500 photos on avg).

Before you start: create a new bookmark in your browser and paste the contents of `google-photo-metadata-dump-bookmarklet.txt` as the URL.

Then, the flow per-window looks like this:

1. Navigate to your target album on Google Photos (web).
2. Open the first photo and ensure the "Info" (i) panel is open.
3. Click the bookmarklet. The script will automatically page through the album, jiggling the UI if it gets stuck, and will download a CSV file when it reaches the end. Save this CSV file to a `scraped/` folder.

If the scraper gets stuck (and because this is a jank script, it _will_, at least a few times) - don't worry. You can just resume scraping from the image it failed on, and then use some of the subsequent scripts to "unify" multiple CSVs from a single album.

### Step 2: Clean and Normalize the CSVs

Because Google Photos has a bunch of different things it likes to shove in the Info box, and because my scraper script is LLM slop, the generated CSV files tend to be pretty inconsistent wrt. what columns they have, what order they're in, etc...

The data is all there (and from testing, accurate), but to make things nicer (particularly for CSV unification), we need to do a normalization pass.

1. **Sanity Check (Optional but recommended):** This will flag if any CSVs you dumped have duplicate rows (which would indicate a bug with the scraper).
   ```bash
   python3 sanity-check-csv.py ./scraped-normalized/
   ```

2. **Normalize:** Strip out junk columns and create a uniform dataset.
   ```bash
   python3 normalize-csv.py ./scraped/
   ```
   *(This will output cleaned files into a `scraped-normalized/` directory).*

3. **Unify:** If your scrape spanned multiple runs and generated multiple CSVs for a single album, merge them together.
   ```bash
   python3 unify-csv.py ./scraped-normalized/
   ```

### Step 3: Run the Immich Fixup Tool

This last tool is written in Rust, because I do _not_ want some LLM slop written in Python touching my precious Immich server lol. LLM slop in Rust is ever so marginally less likely to mess things up too badly tho, lol.

Compile and run the Rust CLI against your Immich server. The tool derives the target album name directly from the CSV filename (e.g., `Scotland Trip-unified.csv` looks for an album named "Scotland Trip").

```bash
cd immich-fixup
cargo run --release -- \
  --server "http://your-immich-server:2283" \
  --api-key "YOUR_IMMICH_API_KEY" \
  --metadata "../scraped-normalized/Your_Album_Name-unified.csv" \
  fix \
  --dry-run
```

If all goes well - congrats! Your Immich albums will look _identical_ when put side-by-side to your Google Photos shared albums, and you can finally stop paying Google for hosting all your photos 🥰
