import argparse

import ujson


def load_input(file_path):
    """Load content from a file."""
    try:
        with open(file_path, "rb") as txfile:
            content = txfile.read().decode("unicode_escape", errors="ignore")
        return content
    except Exception as e:
        print(f"Error loading input file: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="UltraJSON command line utility")
    subparsers = parser.add_subparsers(dest="command", help="API command to use")

    # Common arguments for encoding functions
    encoder_parent = argparse.ArgumentParser(add_help=False)
    encoder_parent.add_argument(
        "--ensure-ascii",
        dest="ensure_ascii",
        action="store_true",
        default=False,
        help="Ensure ASCII output (default: False)",
    )
    encoder_parent.add_argument(
        "--encode-html-chars",
        dest="encode_html_chars",
        action="store_true",
        default=False,
        help="Encode < > & as unicode escape sequences (default: False)",
    )
    encoder_parent.add_argument(
        "--escape-forward-slashes",
        dest="escape_forward_slashes",
        action="store_true",
        default=True,
        help="Escape / characters (default: True)",
    )
    encoder_parent.add_argument(
        "--no-escape-forward-slashes",
        dest="escape_forward_slashes",
        action="store_false",
        help="Don't escape / characters",
    )
    encoder_parent.add_argument(
        "--sort-keys",
        dest="sort_keys",
        action="store_true",
        default=False,
        help="Sort dictionary keys (default: False)",
    )
    encoder_parent.add_argument(
        "--indent", type=int, default=0, help="Indentation level (default: 0)"
    )
    encoder_parent.add_argument(
        "--allow-nan",
        dest="allow_nan",
        action="store_true",
        default=True,
        help="Allow NaN and Infinity values (default: True)",
    )
    encoder_parent.add_argument(
        "--no-allow-nan",
        dest="allow_nan",
        action="store_false",
        help="Don't allow NaN and Infinity values",
    )
    encoder_parent.add_argument(
        "--reject-bytes",
        dest="reject_bytes",
        action="store_true",
        default=False,
        help="Reject bytes objects (default: False)",
    )
    encoder_parent.add_argument(
        "--default",
        type=str,
        help="Python expression, representing a function to handle non-JSON serializable objects",
    )
    encoder_parent.add_argument(
        "--separators",
        type=str,
        help="Two-character string, representing the item separator and key-value separator, e.g., ',,::'",
    )

    # encode/dumps command
    encode_parser = subparsers.add_parser(
        "encode",
        parents=[encoder_parent],
        help="Convert object to JSON string",
        aliases=["dumps"],
    )
    encode_parser.add_argument("input_file", help="Input file to encode")

    # decode/loads command
    decode_parser = subparsers.add_parser(
        "decode", help="Convert JSON string to object", aliases=["loads"]
    )
    decode_parser.add_argument("input_file", help="JSON file to decode")

    # dump command
    dump_parser = subparsers.add_parser(
        "dump",
        parents=[encoder_parent],
        help="Convert object to JSON and write to file",
    )
    dump_parser.add_argument("input_file", help="Input file to encode")
    dump_parser.add_argument("output_file", help="Output file to write JSON")

    # load command
    load_parser = subparsers.add_parser("load", help="Load JSON from file to object")
    load_parser.add_argument("input_file", help="JSON file to load")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # Handle encode/dumps
    if args.command in ["encode", "dumps"]:
        input_data = load_input(args.input_file)
        if input_data is None:
            return

        default_fn = None
        if args.default:
            try:
                default_fn = eval(args.default)
            except Exception as e:
                print(f"Error evaluating default function: {e}")
                return

        separators = None
        if args.separators:
            try:
                parts = args.separators.split(",", 1)
                if len(parts) != 2:
                    print("Error: separators must be two strings separated by comma")
                    return
                separators = (parts[0], parts[1])
            except Exception as e:
                print(f"Error parsing separators: {e}")
                return

        result = ujson.encode(
            input_data,
            ensure_ascii=args.ensure_ascii,
            encode_html_chars=args.encode_html_chars,
            escape_forward_slashes=args.escape_forward_slashes,
            sort_keys=args.sort_keys,
            indent=args.indent,
            allow_nan=args.allow_nan,
            reject_bytes=args.reject_bytes,
            default=default_fn,
            separators=separators,
        )
        print(result)

    # Handle decode/loads
    elif args.command in ["decode", "loads"]:
        input_data = load_input(args.input_file)
        if input_data is None:
            return

        result = ujson.decode(input_data)
        print(result)

    # Handle dump
    elif args.command == "dump":
        input_data = load_input(args.input_file)
        if input_data is None:
            return

        with open(args.output_file, "w") as outfile:
            ujson.dump(
                input_data,
                outfile,
                ensure_ascii=args.ensure_ascii,
                encode_html_chars=args.encode_html_chars,
                escape_forward_slashes=args.escape_forward_slashes,
                sort_keys=args.sort_keys,
                indent=args.indent,
                allow_nan=args.allow_nan,
                reject_bytes=args.reject_bytes,
            )
        print(f"Data successfully written to {args.output_file}")

    # Handle load
    elif args.command == "load":
        with open(args.input_file) as infile:
            result = ujson.load(infile)
        print(result)


if __name__ == "__main__":
    main()
