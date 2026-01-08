from PIL import Image, ImageDraw, ImageFont

# Create a dark blue image
width, height = 400, 200
background_color = "#0B2447" # Dark Blue
image = Image.new("RGB", (width, height), background_color)

draw = ImageDraw.Draw(image)

# Add Text "Rend"
text = "Rend"
text_color = "white"

# Try to load a nice font, fallback to default
try:
    font = ImageFont.truetype("arial.ttf", 60)
except IOError:
    font = ImageFont.load_default()

# Calculate text position (Center)
bbox = draw.textbbox((0, 0), text, font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]
x = (width - text_width) // 2
y = (height - text_height) // 2

draw.text((x, y), text, fill=text_color, font=font)

# Save
image.save("splash.png")
print("splash.png created")
