library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_bench is
end entity;
architecture sim of tb_bench is
  signal clk : std_logic := '0';
  signal cnt : unsigned(31 downto 0) := (others => '0');
  signal data32 : std_logic_vector(31 downto 0);
begin
  clk <= not clk after 5 ns;
  p : process(clk)
  begin
    if rising_edge(clk) then
      cnt <= cnt + 1;
      data32 <= std_logic_vector(cnt);
    end if;
  end process;
  p_end : process
  begin
    wait for 2 ms;
    report "bench done" severity note;
    stop;
  end process;
end architecture;
