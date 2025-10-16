# create_10gb_file.py
size_gb = 10
block_size = 1024 * 1024  # 1 MB
total_blocks = size_gb * 1024

with open("ten-gig.bin", "wb") as f:
    for i in range(total_blocks):
        f.write(b"\0" * block_size)
        if i % 512 == 0:
            print(f"{i/1024:.1f} GB written")
