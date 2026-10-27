"""Rebuild the README animation. Optional dependency: pip install Pillow."""
from pathlib import Path
from math import hypot
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]

def curve(a, b, c, d, steps=100):
    return [tuple((1-t)**3*a[j]+3*(1-t)**2*t*b[j]+3*(1-t)*t*t*c[j]+t**3*d[j]
                  for j in range(2)) for t in (i/steps for i in range(steps+1))]

def position(points, fraction):
    lengths = [hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(points,points[1:])]
    distance = fraction*sum(lengths)
    for a,b,length in zip(points,points[1:],lengths):
        if distance <= length and length:
            return tuple(a[j]+(b[j]-a[j])*distance/length for j in range(2))
        distance -= length
    return points[-1]

def main():
    base = Image.open(ROOT/'assets/workflow-overview.png').convert('L').convert('RGB')
    # Arrow centerlines in the original 1536 x 1024 artwork.
    upper = [(735,361),(800,361)] + curve((800,361),(900,361),(900,267),(990,267)) + [(1061,267)]
    trunk = curve((735,361),(843,357),(869,381),(869,449)) + [(869,566)]
    left = trunk + curve((869,566),(869,606),(809,612),(743,612)) + curve((743,612),(700,612),(686,630),(686,665))
    right = trunk + curve((869,566),(869,609),(905,612),(954,612)) + curve((954,612),(1006,612),(1014,639),(1014,665))
    paths = [[(328,361),(522,361)],upper,left,right,
             [(495,960),(543,960)],[(773,960),(820,960)],[(1017,960),(1066,960)]]
    scale = 0.75
    base = base.resize((1152,768),Image.Resampling.LANCZOS)
    # Fixed grayscale palette plus red avoids flickering and preserves sharp text.
    palette = Image.new('P',(1,1))
    colors = [v for i in range(255) for v in (i,i,i)] + [215,35,40]
    palette.putpalette(colors)
    frames = []
    for frame in range(80):
        canvas = base.copy()
        draw = ImageDraw.Draw(canvas)
        for n,path in enumerate(paths):
            phase = (frame/80 + (0.0 if n < 4 else 0.15)) % 1
            x,y = position(path,phase)
            x,y = x*scale,y*scale
            radius = 5 if n >= 4 else 6
            draw.ellipse((x-radius-1,y-radius-1,x+radius+1,y+radius+1),fill='white')
            draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=(215,35,40))
        frames.append(canvas.quantize(palette=palette,dither=Image.Dither.NONE))
    output = ROOT/'assets/workflow-overview.gif'
    frames[0].save(output,save_all=True,append_images=frames[1:],duration=50,loop=0,optimize=True,disposal=1)
    print(f'Created {output.name}: {output.stat().st_size:,} bytes, 80 frames, 4 second loop')

if __name__ == '__main__':
    main()
