import os
import click
from .assembler import Assembler

@click.command('mxsm')
@click.option('-o', '--output', type=click.Path(exists=True, dir_okay=True), help="Directory to save the assembled binary files.", default="./build")
@click.option('--debug', is_flag=True, default=False, help="Print debug information after assembly.")
@click.option('--prod_file', type=click.Path(exists=True, file_okay=True, resolve_path=True), required=True)
@click.argument('input_file', type=click.Path(exists=True, file_okay=True, resolve_path=True), required=True)
def main(input_file, prod_file, output, debug):
    """
    MXSM - MX Cross Assembler

    2-Pass Cross Architecture Assembler for MX Architecture
    
    INPUT_FILE: Path to the MX assembly file.
    """
    try:
        # Read the assembler code
        with open(input_file, 'r') as f:
            code = f.read()

        # Read the production mapping
        with open(prod_file, 'r') as f:
            prod = f.read()

        # Create an Assembler instance
        asm = Assembler(code, prod)
        asm.assemble()

        with open(os.path.join(f"{os.path.realpath(output)}", 'ins.bin'), 'wb') as f:
            f.write(asm.ins)

        with open(os.path.join(f"{os.path.realpath(output)}", 'data.bin'), 'wb') as f:
            f.write(asm.data)
    except Exception as e:
        raise click.ClickException(str(e))


if __name__ == '__main__':
    main()