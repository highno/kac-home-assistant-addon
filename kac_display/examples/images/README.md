# Image files

Place local source images in the add-on configuration folder and enter their paths in the graphical **Image pages** section. Existing legacy installations may still reference them from `kac.yaml`.

The bridge accepts formats Pillow can read, including PNG, JPG, WebP, and GIF. Still images are converted to a 240×240 baseline JPG. Animated inputs are converted to a 240×240 GIF. The KAC firmware itself accepts only its documented JPG/GIF image-page formats.
