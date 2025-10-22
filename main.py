import diver
import pathlib as path


if __name__ == "__main__":
    diver = diver.Diver()
    print(f"Start: {diver.start}")
    print(f"Goal: {diver.dest}")

    Pth = diver.a_star_search(max_depth=6)
    print("\nPath found:")
    print(" → ".join(Pth) if Pth else "No path found")
    diver.save_memory()
    print("\nAll pages visited:")
    for k, v in diver.all_paths.items():
        print(f"{k}: {len(v)} links found")

