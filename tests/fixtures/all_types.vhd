library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity tb_wave is
end entity;

architecture sim of tb_wave is
  type t_fsm is (IDLE, RUN, DONE);
  signal clk      : std_logic := '0';
  signal cnt      : unsigned(3 downto 0) := (others => '0');
  signal state    : t_fsm := IDLE;
  signal payload  : std_logic_vector(7 downto 0) := (others => '0');
  signal data     : std_logic_vector(63 downto 0) := (others => 'X');
  signal real_sig : real := 0.0;
  signal lbl      : string(1 to 3);
begin
  clk <= not clk after 5 ns;

  p_counter : process(clk)
  begin
    if rising_edge(clk) then
      cnt <= cnt + 1;
    end if;
  end process;

  p_fsm : process(clk)
  begin
    if rising_edge(clk) then
      case state is
        when IDLE  => state <= RUN;
        when RUN   =>
          payload <= std_logic_vector(cnt) & "0110";
          state   <= DONE;
        when DONE  => state <= IDLE;
      end case;
    end if;
  end process;

  p_data : process(clk)
  begin
    if rising_edge(clk) then
      if cnt = 0 then
        data <= X"0123456789ABCDEF";
      elsif cnt = 8 then
        data <= X"FFFFFFFFFFFFFFFF";
      end if;
    end if;
  end process;

  p_real : process(clk)
  begin
    if rising_edge(clk) then
      real_sig <= real(to_integer(cnt)) * 0.5;
    end if;
  end process;

  p_label : process
  begin
    wait for 500 ns;
    lbl <= "OK!";
  end process;

  p_end : process
  begin
    wait for 1 us;
    report "wave spike done" severity note;
    stop;
  end process;
end architecture;