# suganami_mirei_twitter_backup

This repository contains an X/Twitter archive page generated from `gallery-dl` data.

## Local Usage

Fetch or update the archive data:

```bash
bash backup.sh
```

Generate the static page:

```bash
bash gen.sh
```

The default output path is:

```text
output/suganami_mirei/timeline.html
```

## GitHub Pages Deployment

This repository already includes `.github/workflows/deploy-pages.yml`:

- Every push to the default branch runs `gen.sh` with GitHub Actions
- The workflow generates the page with external media URLs that point to the repository's raw files
- Only the generated site is uploaded as a Pages artifact, so deployment stays much lighter than copying the entire `gallery-dl/` directory
- The generated timeline is published directly at the Pages root URL

Local generation still uses relative media paths by default, so you can browse the archive offline from your own checkout.

You still need to confirm the Pages setting once in GitHub:

1. Open `Settings`
2. Go to `Pages`
3. Set the source to `GitHub Actions`

## Uploading Archive Data in Batches

`gallery-dl/` is ignored by default in `.gitignore` so the entire archive is not re-added to Git all at once.

If you want to upload archive data in batches, use the helper script to force-add files by filename prefix, commit them, and optionally push them immediately:

```bash
bash stage_data_prefix.sh --commit meta
bash stage_data_prefix.sh --commit --push 109
```

You can also let the script process multiple batches in sequence:

```bash
bash stage_data_prefix.sh --commit --push 110 111 112
```

If you do not want to type every later prefix manually, use `--auto` and provide only the starting prefix:

```bash
bash stage_data_prefix.sh --commit --push --auto 109
```

This starts at `109` and continues through later prefixes with the same number of digits in order.

You can inspect the batch sizes first with a dry run:

```bash
bash stage_data_prefix.sh --dry-run 109 110 111
```

Using 3-digit prefixes such as `109`, `110`, and `111` is recommended. Uploading the entire `1*` range at once is still too large for a normal Git push.
