/* SPDX-License-Identifier: Apache-2.0 */
/* The STM32F042F6's memory (datasheet DS10152, section 3.4): 32 KB of
   flash and 6 KB of SRAM. cortex-m-rt's link.x includes this file. */
MEMORY
{
  FLASH : ORIGIN = 0x08000000, LENGTH = 32K
  RAM   : ORIGIN = 0x20000000, LENGTH = 6K
}
