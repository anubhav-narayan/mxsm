import os
import click
import pprint
from .assembler import Assembler
from .disassembler import Disassembler

@click.command('mxsm')
@click.option('-d', '--disassemble', is_flag=True, default=False, help="Run the Disassembler instead of assembler")
@click.option('-o', '--output', type=click.Path(exists=True, dir_okay=True, resolve_path=True), help="Directory to save the assembled binary files.", default="./build", show_default=True)
@click.option('--format', 'output_format', type=click.Choice(['raw', 'object', 'packed']), default='raw', show_default=True, help="Assembler output format.")
@click.option('--debug', is_flag=True, default=False, help="Print debug information after assembly.")
@click.argument('input-file', type=click.Path(exists=True, file_okay=True, resolve_path=True), required=True)
@click.argument('isa-file', type=click.Path(exists=True, file_okay=True, resolve_path=True), default="./isa.json")
def main(input_file, isa_file, output, output_format, debug, disassemble):
    """
    MXSM - MX Cross Assembler/Disassembler

    2-Pass Cross Architecture Assembler for MX Architecture
    
    INPUT_FILE: Path to the MX assembly file.
    
    ISA_FILE: ISA definition file in JSON. [default: ./isa.json]
    """
    try:
        # Read the code
        if disassemble:
            with open(input_file, 'rb') as f:
                code = f.read()
        else:
            with open(input_file, 'r') as f:
                code = f.read()

        # Read the production mapping
        with open(isa_file, 'r') as f:
            isa = f.read()

        if disassemble:
            dsm = Disassembler(isa)
            dsm.disassemble(code)

            with open(os.path.join(f"{os.path.realpath(output)}", 'ins_dec.mx11'), 'w') as f:
                f.write(dsm.string_decoding)

            if debug:
                click.echo(dsm.dec)
        else:
            asm = Assembler(isa)
            if output_format == 'object':
                object_file = asm.assemble_binary_object(code)
                with open(os.path.join(f"{os.path.realpath(output)}", 'program.mxo'), 'wb') as f:
                    f.write(object_file)
            elif output_format == 'packed':
                import json
                packed_object_file = asm.assemble_object(code, packed=True)
                packed_object_file = json.dumps(packed_object_file, indent=2)
                with open(os.path.join(f"{os.path.realpath(output)}", 'program.mxp'), 'w') as f:
                    f.write(packed_object_file)
            else:
                asm.assemble(code)

                with open(os.path.join(f"{os.path.realpath(output)}", 'ins.bin'), 'wb') as f:
                    f.write(asm.ins)

                with open(os.path.join(f"{os.path.realpath(output)}", 'data.bin'), 'wb') as f:
                    f.write(asm.data)

            if debug:
                click.echo(pprint.pformat(asm.debug_info))
    except Exception as e:
        raise click.ClickException(str(e))


if __name__ == '__main__':
    main()